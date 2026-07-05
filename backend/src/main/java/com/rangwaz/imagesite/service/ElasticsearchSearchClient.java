package com.rangwaz.imagesite.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.config.SearchProperties;
import com.rangwaz.imagesite.entity.ImageSearchDocumentEntity;
import com.rangwaz.imagesite.entity.SearchSuggestionEntity;
import org.springframework.stereotype.Component;
import org.springframework.util.CollectionUtils;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Elasticsearch-backed search API used as the primary search path.
 */
@Component
public class ElasticsearchSearchClient {
    private final SearchProperties properties;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public ElasticsearchSearchClient(SearchProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(properties.getConnectTimeoutMs()))
                .build();
    }

    /**
     * Ensures the image search index exists.
     */
    public void ensureIndex() {
        int status = status("HEAD", "/" + properties.getIndexName());
        if (status == 200) return;
        if (status != 404) throw new BusinessException("SEARCH_ENGINE_ERROR", "Elasticsearch index check failed: " + status);
        String physicalName = versionedIndexName();
        requestJson("PUT", "/" + physicalName, indexDefinition());
        swapAlias(physicalName);
    }

    /**
     * Recreates the image index for a clean full reindex.
     */
    public void recreateIndex() {
        String physicalName = versionedIndexName();
        requestJson("PUT", "/" + physicalName, indexDefinition());
        swapAlias(physicalName);
    }

    /**
     * Searches image ids from Elasticsearch.
     *
     * @param keywords expanded query keywords
     * @param limit maximum image ids
     * @return image ids in relevance order
     */
    public List<Long> searchImageIds(List<String> keywords, int limit) {
        String query = joinKeywords(keywords);
        if (!StringUtils.hasText(query)) return List.of();
        List<Object> should = new ArrayList<>();
        should.add(map("multi_match", map(
                "query", query,
                "type", "best_fields",
                "fields", List.of(
                        "title^5",
                        "intentKeywords^7",
                        "tags^5",
                        "categories^4",
                        "topics^4",
                        "suggestText^3",
                        "description^2",
                        "content",
                        "authorNickname"
                )
        )));
        for (String keyword : keywords) {
            if (!StringUtils.hasText(keyword)) continue;
            should.add(map("term", map("suggestKeywords", map("value", keyword, "boost", 8))));
            should.add(map("term", map("intentKeywords", map("value", keyword, "boost", 10))));
        }
        Map<String, Object> body = map(
                "size", Math.max(1, limit),
                "_source", false,
                "query", map("bool", map(
                        "filter", List.of(map("term", map("status", "PUBLISHED"))),
                        "should", should,
                        "minimum_should_match", 1
                )),
                "sort", List.of(
                        map("_score", "desc"),
                        map("hotScore", map("order", "desc")),
                        map("publishedAt", map("order", "desc"))
                )
        );
        JsonNode response = requestJson("POST", "/" + properties.getIndexName() + "/_search", body);
        List<Long> ids = new ArrayList<>();
        for (JsonNode hit : response.path("hits").path("hits")) {
            String id = hit.path("_id").asText();
            if (StringUtils.hasText(id)) ids.add(Long.parseLong(id));
        }
        return ids;
    }

    /**
     * Suggests keyword chips from indexed metadata.
     *
     * @param keywords optional query keywords
     * @param limit maximum keyword count
     * @return keyword suggestions
     */
    public List<SearchSuggestionEntity> suggestKeywords(List<String> keywords, int limit) {
        String query = joinKeywords(keywords);
        Map<String, Object> bool = map("filter", List.of(map("term", map("status", "PUBLISHED"))));
        if (StringUtils.hasText(query)) {
            bool.put("must", List.of(map("multi_match", map(
                    "query", query,
                    "fields", List.of("suggestText^4", "title^2", "tags^4", "categories^3", "topics^3")
            ))));
        }
        Map<String, Object> body = map(
                "size", 0,
                "query", map("bool", bool),
                "aggs", map("keywords", map("terms", map(
                        "field", "suggestKeywords",
                        "size", Math.max(1, limit)
                )))
        );
        JsonNode response = requestJson("POST", "/" + properties.getIndexName() + "/_search", body);
        List<SearchSuggestionEntity> suggestions = new ArrayList<>();
        for (JsonNode bucket : response.path("aggregations").path("keywords").path("buckets")) {
            SearchSuggestionEntity item = new SearchSuggestionEntity();
            item.setKeyword(bucket.path("key").asText());
            item.setKind("keyword");
            item.setPostCount(bucket.path("doc_count").asLong());
            suggestions.add(item);
        }
        return suggestions;
    }

    /**
     * Bulk indexes image documents.
     *
     * @param documents image search documents
     */
    public void bulkIndex(List<ImageSearchDocumentEntity> documents) {
        if (CollectionUtils.isEmpty(documents)) return;
        StringBuilder ndjson = new StringBuilder();
        for (ImageSearchDocumentEntity document : documents) {
            try {
                ndjson.append(objectMapper.writeValueAsString(map("index", map(
                        "_index", properties.getIndexName(),
                        "_id", String.valueOf(document.getId())
                )))).append('\n');
                ndjson.append(objectMapper.writeValueAsString(toDocument(document))).append('\n');
            } catch (IOException exception) {
                throw new BusinessException("SEARCH_INDEX_ERROR", "failed to serialize search document");
            }
        }
        JsonNode response = requestNdjson("/_bulk", ndjson.toString());
        if (response.path("errors").asBoolean(false)) {
            throw new BusinessException("SEARCH_INDEX_ERROR", "Elasticsearch bulk index failed");
        }
    }

    private Map<String, Object> toDocument(ImageSearchDocumentEntity source) {
        List<String> tags = splitCsv(source.getTagsCsv());
        List<String> topics = splitCsv(source.getTopicsCsv());
        List<String> categories = StringUtils.hasText(source.getCategoryName()) ? List.of(source.getCategoryName()) : List.of();
        List<String> intentKeywords = deriveIntentKeywords(source, tags, topics, categories);
        LinkedHashSet<String> suggestKeywords = new LinkedHashSet<>();
        suggestKeywords.addAll(intentKeywords);
        suggestKeywords.addAll(categories);
        suggestKeywords.addAll(tags);
        suggestKeywords.addAll(topics);
        List<String> searchText = new ArrayList<>();
        searchText.add(source.getTitle());
        searchText.add(source.getDescription());
        searchText.add(source.getContent());
        searchText.add(source.getAuthorNickname());
        searchText.add(source.getCategoryName());
        searchText.addAll(tags);
        searchText.addAll(topics);
        searchText.addAll(intentKeywords);
        return map(
                "id", source.getId(),
                "authorId", source.getAuthorId(),
                "status", source.getStatus(),
                "title", valueOrEmpty(source.getTitle()),
                "content", valueOrEmpty(source.getContent()),
                "description", valueOrEmpty(source.getDescription()),
                "authorUsername", valueOrEmpty(source.getAuthorUsername()),
                "authorNickname", valueOrEmpty(source.getAuthorNickname()),
                "width", source.getWidth(),
                "height", source.getHeight(),
                "ratio", valueOrEmpty(source.getRatio()),
                "orientation", orientation(source.getWidth(), source.getHeight()),
                "categories", categories,
                "tags", tags,
                "topics", topics,
                "intentKeywords", intentKeywords,
                "suggestKeywords", new ArrayList<>(suggestKeywords),
                "suggestText", joinKeywords(searchText),
                "fileUrl", source.getFileUrl(),
                "thumbnailUrl", source.getThumbnailUrl(),
                "hotScore", source.getHotScore() == null ? 0 : source.getHotScore().doubleValue(),
                "publishedAt", source.getPublishedAt(),
                "createdAt", source.getCreatedAt()
        );
    }

    private JsonNode requestJson(String method, String path, Object body) {
        try {
            String payload = body == null ? "" : (body instanceof String text ? text : objectMapper.writeValueAsString(body));
            HttpRequest.Builder builder = HttpRequest.newBuilder(uri(path))
                    .timeout(Duration.ofMillis(properties.getReadTimeoutMs()))
                    .header("Accept", "application/json");
            if (body == null) {
                builder.method(method, HttpRequest.BodyPublishers.noBody());
            } else {
                builder.header("Content-Type", "application/json");
                builder.method(method, HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8));
            }
            HttpResponse<String> response = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 300) {
                throw new BusinessException("SEARCH_ENGINE_ERROR", "Elasticsearch request failed: " + response.statusCode());
            }
            return StringUtils.hasText(response.body()) ? objectMapper.readTree(response.body()) : objectMapper.createObjectNode();
        } catch (IOException exception) {
            throw new BusinessException("SEARCH_ENGINE_ERROR", "Elasticsearch request failed");
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new BusinessException("SEARCH_ENGINE_ERROR", "Elasticsearch request interrupted");
        }
    }

    private JsonNode requestNdjson(String path, String body) {
        try {
            HttpRequest request = HttpRequest.newBuilder(uri(path))
                    .timeout(Duration.ofMillis(properties.getReadTimeoutMs()))
                    .header("Accept", "application/json")
                    .header("Content-Type", "application/x-ndjson")
                    .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() >= 300) {
                throw new BusinessException("SEARCH_ENGINE_ERROR", "Elasticsearch bulk request failed: " + response.statusCode());
            }
            return objectMapper.readTree(response.body());
        } catch (IOException exception) {
            throw new BusinessException("SEARCH_ENGINE_ERROR", "Elasticsearch bulk request failed");
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new BusinessException("SEARCH_ENGINE_ERROR", "Elasticsearch bulk request interrupted");
        }
    }

    private int status(String method, String path) {
        try {
            HttpRequest request = HttpRequest.newBuilder(uri(path))
                    .timeout(Duration.ofMillis(properties.getReadTimeoutMs()))
                    .method(method, HttpRequest.BodyPublishers.noBody())
                    .build();
            return httpClient.send(request, HttpResponse.BodyHandlers.discarding()).statusCode();
        } catch (IOException exception) {
            throw new BusinessException("SEARCH_ENGINE_ERROR", "Elasticsearch is unavailable");
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new BusinessException("SEARCH_ENGINE_ERROR", "Elasticsearch request interrupted");
        }
    }

    private URI uri(String path) {
        String base = properties.getElasticsearchUrl().replaceAll("/+$", "");
        return URI.create(base + path);
    }

    private void swapAlias(String physicalName) {
        List<Object> actions = new ArrayList<>();
        for (String oldIndex : aliasIndices()) {
            actions.add(map("remove", map("index", oldIndex, "alias", properties.getIndexName())));
        }
        actions.add(map("add", map("index", physicalName, "alias", properties.getIndexName())));
        requestJson("POST", "/_aliases", map("actions", actions));
    }

    private List<String> aliasIndices() {
        int status = status("HEAD", "/_alias/" + properties.getIndexName());
        if (status == 404) return List.of();
        if (status != 200) throw new BusinessException("SEARCH_ENGINE_ERROR", "Elasticsearch alias check failed: " + status);
        JsonNode response = requestJson("GET", "/_alias/" + properties.getIndexName(), null);
        List<String> indices = new ArrayList<>();
        response.fieldNames().forEachRemaining(indices::add);
        return indices;
    }

    private String versionedIndexName() {
        return properties.getIndexName() + "-v" + System.currentTimeMillis();
    }

    private static List<String> splitCsv(String csv) {
        if (!StringUtils.hasText(csv)) return List.of();
        LinkedHashSet<String> values = new LinkedHashSet<>();
        for (String part : csv.split(",")) {
            String trimmed = part.trim();
            if (StringUtils.hasText(trimmed)) values.add(trimmed);
        }
        return new ArrayList<>(values);
    }

    private static List<String> deriveIntentKeywords(ImageSearchDocumentEntity source,
                                                     List<String> tags,
                                                     List<String> topics,
                                                     List<String> categories) {
        List<String> sourceText = new ArrayList<>();
        sourceText.add(source.getTitle());
        sourceText.add(source.getDescription());
        sourceText.add(source.getContent());
        sourceText.add(source.getAuthorNickname());
        sourceText.add(source.getCategoryName());
        sourceText.add(joinKeywords(tags));
        sourceText.add(joinKeywords(topics));
        sourceText.add(joinKeywords(categories));
        String text = joinKeywords(sourceText).toLowerCase(Locale.ROOT);
        String orientation = orientation(source.getWidth(), source.getHeight());
        boolean squareLike = "square".equals(orientation);
        boolean portraitLike = "portrait".equals(orientation) || squareLike;
        boolean portraitSubject = containsAny(text,
                "人像", "人物", "女生", "女孩", "女性", "男生", "男孩", "男性", "自拍", "脸", "面部", "肖像",
                "头像", "动漫", "卡通", "插画", "二次元", "猫", "狗", "宠物", "动物",
                "portrait", "avatar", "girl", "boy", "anime", "cartoon", "cat", "dog", "pet");
        boolean backgroundSubject = containsAny(text,
                "壁纸", "背景", "风景", "自然", "天空", "海", "山", "森林", "花", "城市", "夜景", "极简",
                "wallpaper", "background", "landscape", "sky", "aesthetic");
        boolean fashionSubject = containsAny(text,
                "穿搭", "穿着", "服装", "衣服", "时尚", "街拍", "模特", "裙", "外套", "牛仔", "outfit", "fashion", "streetwear");
        boolean roomSubject = containsAny(text, "房间", "卧室", "客厅", "家居", "室内", "装修", "interior", "room", "home decor");

        LinkedHashSet<String> values = new LinkedHashSet<>();
        if (portraitLike && portraitSubject) {
            values.add("头像");
            values.add("头像素材");
            values.add("人像头像");
            values.add("profile picture");
            values.add("avatar");
            if (containsAny(text, "女生", "女孩", "女性", "girl")) values.add("女生头像");
            if (containsAny(text, "男生", "男孩", "男性", "boy")) values.add("男生头像");
            if (containsAny(text, "动漫", "卡通", "插画", "二次元", "anime", "cartoon")) values.add("卡通头像");
        }
        if (backgroundSubject || ("portrait".equals(orientation) && !fashionSubject)) {
            values.add("壁纸");
            values.add("高清壁纸");
            values.add("背景图");
            if ("portrait".equals(orientation)) values.add("手机壁纸");
            if (containsAny(text, "动漫", "插画", "二次元", "anime")) values.add("动漫壁纸");
            if (containsAny(text, "自然", "风景", "天空", "海", "山", "森林", "landscape", "sky")) values.add("自然壁纸");
        }
        if (fashionSubject) {
            values.add("穿搭");
            values.add("穿搭灵感");
            values.add("时尚穿搭");
            values.add("outfit");
        }
        if (roomSubject) {
            values.add("房间设计");
            values.add("家居灵感");
            values.add("室内设计");
        }
        values.add(orientation);
        return new ArrayList<>(values);
    }

    private static String orientation(Integer width, Integer height) {
        if (width == null || height == null || width <= 0 || height <= 0) return "unknown";
        double ratio = width.doubleValue() / height.doubleValue();
        if (ratio >= 0.88D && ratio <= 1.12D) return "square";
        return ratio < 1D ? "portrait" : "landscape";
    }

    private static boolean containsAny(String text, String... needles) {
        if (!StringUtils.hasText(text)) return false;
        for (String needle : needles) {
            if (StringUtils.hasText(needle) && text.contains(needle.toLowerCase(Locale.ROOT))) return true;
        }
        return false;
    }

    private static String valueOrEmpty(String value) {
        return value == null ? "" : value;
    }

    private static String joinKeywords(List<String> values) {
        return values.stream()
                .filter(StringUtils::hasText)
                .map(String::trim)
                .distinct()
                .reduce("", (left, right) -> left.isEmpty() ? right : left + " " + right);
    }

    private static Map<String, Object> map(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < pairs.length; index += 2) {
            result.put((String) pairs[index], pairs[index + 1]);
        }
        return result;
    }

    private static String indexDefinition() {
        return """
                {
                  "settings": {
                    "index": { "max_ngram_diff": 4 },
                    "analysis": {
                      "tokenizer": {
                        "cjk_ngram_tokenizer": {
                          "type": "ngram",
                          "min_gram": 1,
                          "max_gram": 3,
                          "token_chars": ["letter", "digit"]
                        }
                      },
                      "analyzer": {
                        "cjk_ngram": {
                          "tokenizer": "cjk_ngram_tokenizer",
                          "filter": ["lowercase"]
                        }
                      }
                    }
                  },
                  "mappings": {
                    "properties": {
                      "id": { "type": "long" },
                      "authorId": { "type": "long" },
                      "status": { "type": "keyword" },
                      "title": { "type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard" },
                      "content": { "type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard" },
                      "description": { "type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard" },
                      "authorUsername": { "type": "keyword" },
                      "authorNickname": { "type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard" },
                      "width": { "type": "integer" },
                      "height": { "type": "integer" },
                      "ratio": { "type": "keyword" },
                      "orientation": { "type": "keyword" },
                      "categories": { "type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard" },
                      "tags": { "type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard" },
                      "topics": { "type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard" },
                      "intentKeywords": { "type": "keyword" },
                      "suggestKeywords": { "type": "keyword" },
                      "suggestText": { "type": "text", "analyzer": "cjk_ngram", "search_analyzer": "standard" },
                      "fileUrl": { "type": "keyword", "index": false },
                      "thumbnailUrl": { "type": "keyword", "index": false },
                      "hotScore": { "type": "double" },
                      "publishedAt": { "type": "date" },
                      "createdAt": { "type": "date" }
                    }
                  }
                }
                """;
    }
}
