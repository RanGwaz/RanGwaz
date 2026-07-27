package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.SearchSuggestionEntity;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import com.rangwaz.imagesite.service.ContentSafetyService;
import com.rangwaz.imagesite.service.ElasticsearchSearchClient;
import com.rangwaz.imagesite.service.SearchService;
import com.rangwaz.imagesite.service.TopicService;
import com.rangwaz.imagesite.service.UserService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;

/**
 * Default global search service implementation.
 */
@Service
public class SearchServiceImpl implements SearchService {
    private static final Logger log = LoggerFactory.getLogger(SearchServiceImpl.class);
    private static final int SEARCH_IMAGE_LIMIT = 180;
    private static final int RELATED_LIMIT = 18;

    private static final List<String> DEFAULT_IDEAS = List.of(
            "头像", "壁纸", "穿搭", "时尚摄影", "街头摄影", "房间设计",
            "自然摄影", "动漫壁纸", "女生头像", "手机壁纸", "唯美壁纸", "家居灵感"
    );

    private static final List<IntentRule> INTENT_RULES = List.of(
            new IntentRule(
                    List.of("头像", "avatar", "pfp", "profile picture"),
                    List.of("头像", "人像", "肖像", "人物", "脸部", "半身", "自拍", "动漫头像", "卡通头像", "portrait", "avatar", "pfp"),
                    List.of("女生头像", "男生头像", "卡通头像", "动漫头像", "可爱头像", "情侣头像", "黑白头像", "氛围感头像", "头像女", "头像男")
            ),
            new IntentRule(
                    List.of("壁纸", "wallpaper", "背景", "锁屏"),
                    List.of("壁纸", "手机壁纸", "高清壁纸", "锁屏壁纸", "背景图", "竖屏", "自然壁纸", "动漫壁纸", "wallpaper", "background"),
                    List.of("手机壁纸", "高清壁纸", "动漫壁纸", "自然壁纸", "极简壁纸", "可爱壁纸", "电脑壁纸", "锁屏壁纸", "唯美壁纸", "背景图")
            ),
            new IntentRule(
                    List.of("穿搭", "穿着", "服装", "衣服", "时尚", "outfit", "fashion"),
                    List.of("穿搭", "穿着", "服装", "衣服", "时尚", "街拍", "模特", "outfit", "fashion", "streetwear"),
                    List.of("女生穿搭", "男生穿搭", "日常穿搭", "韩系穿搭", "街头穿搭", "夏季穿搭", "极简穿搭", "复古穿搭", "通勤穿搭")
            ),
            new IntentRule(
                    List.of("房间", "家居", "室内", "装修", "room", "interior"),
                    List.of("房间", "家居", "室内设计", "卧室", "客厅", "装修", "room", "interior", "home decor"),
                    List.of("卧室设计", "小房间设计", "客厅设计", "家居灵感", "室内设计", "温馨房间", "极简家居", "书桌布置")
            )
    );

    private final ImageContentMapper imageContentMapper;
    private final ImageServiceImpl imageService;
    private final UserService userService;
    private final TopicService topicService;
    private final ElasticsearchSearchClient searchClient;
    private final ContentSafetyService contentSafetyService;

    /**
     * Creates the search service.
     *
     * @param imageContentMapper image content mapper
     * @param imageService post service
     * @param userService user service
     * @param topicService topic service
     * @param searchClient Elasticsearch search client
     * @param contentSafetyService content safety service
     */
    public SearchServiceImpl(ImageContentMapper imageContentMapper,
                             ImageServiceImpl imageService,
                             UserService userService,
                             TopicService topicService,
                             ElasticsearchSearchClient searchClient,
                             ContentSafetyService contentSafetyService) {
        this.imageContentMapper = imageContentMapper;
        this.imageService = imageService;
        this.userService = userService;
        this.topicService = topicService;
        this.searchClient = searchClient;
        this.contentSafetyService = contentSafetyService;
    }

    /**
     * Searches posts, users, and topics.
     *
     * @param keyword keyword
     * @return search result
     */
    @Override
    public ApiDtos.SearchResult search(String keyword) {
        String trimmed = normalize(keyword);
        if (!StringUtils.hasText(trimmed)) {
            return new ApiDtos.SearchResult(List.of(), List.of(), topicService.trending(12), List.of());
        }
        if (!contentSafetyService.allowsText(trimmed)) {
            return new ApiDtos.SearchResult(List.of(), List.of(), List.of(), List.of());
        }
        SearchQueryPlan plan = plan(trimmed);
        List<ApiDtos.ImageView> posts;
        try {
            List<Long> imageIds = searchClient.searchImageIds(plan.searchKeywords(), SEARCH_IMAGE_LIMIT);
            posts = imageIds.isEmpty()
                    ? List.of()
                    : imageService.toViews(imageContentMapper.findPublishedByIds(imageIds), "search");
        } catch (RuntimeException exception) {
            log.warn("Elasticsearch image search failed; using MySQL metadata fallback", exception);
            posts = imageService.toViews(
                    imageContentMapper.search(trimmed, SEARCH_IMAGE_LIMIT),
                    "search-fallback"
            );
            return new ApiDtos.SearchResult(
                    userService.search(trimmed, 12),
                    posts,
                    topicService.search(trimmed, 12),
                    relatedItems(plan, List.of())
            );
        }
        return new ApiDtos.SearchResult(
                userService.search(trimmed, 12),
                posts,
                topicService.search(trimmed, 12),
                relatedItems(plan, suggestKeywords(plan.searchKeywords(), RELATED_LIMIT))
        );
    }

    /**
     * Suggests search ideas for the focused global search box.
     *
     * @param keyword optional typed keyword
     * @return grouped search suggestions
     */
    @Override
    public ApiDtos.SearchSuggestionResponse suggestions(String keyword) {
        String trimmed = normalize(keyword);
        if (!StringUtils.hasText(trimmed)) {
            return new ApiDtos.SearchSuggestionResponse(toSuggestionItems(suggestKeywords(DEFAULT_IDEAS, 12)), List.of());
        }
        if (!contentSafetyService.allowsText(trimmed)) {
            return new ApiDtos.SearchSuggestionResponse(List.of(), List.of());
        }
        SearchQueryPlan plan = plan(trimmed);
        return new ApiDtos.SearchSuggestionResponse(
                relatedItems(plan, suggestKeywords(plan.searchKeywords(), 12)),
                List.of()
        );
    }

    private List<SearchSuggestionEntity> suggestKeywords(List<String> keywords, int limit) {
        try {
            return searchClient.suggestKeywords(keywords, limit);
        } catch (RuntimeException exception) {
            log.warn("Elasticsearch suggestions failed; using MySQL metadata fallback", exception);
            return imageContentMapper.suggestByMetadata(keywords, limit);
        }
    }

    private SearchQueryPlan plan(String keyword) {
        LinkedHashSet<String> searchKeywords = new LinkedHashSet<>();
        LinkedHashSet<String> relatedKeywords = new LinkedHashSet<>();
        searchKeywords.add(keyword);
        for (String part : keyword.split("[\\s,，]+")) {
            if (StringUtils.hasText(part)) searchKeywords.add(part.trim());
        }

        String lower = keyword.toLowerCase(Locale.ROOT);
        boolean matchedIntent = false;
        for (IntentRule rule : INTENT_RULES) {
            if (rule.matches(lower)) {
                matchedIntent = true;
                searchKeywords.addAll(rule.expansions());
                relatedKeywords.addAll(rule.related());
            }
        }
        if (!matchedIntent) {
            relatedKeywords.add(keyword + "壁纸");
            relatedKeywords.add(keyword + "头像");
            relatedKeywords.add(keyword + "插画");
            relatedKeywords.add(keyword + "摄影");
            relatedKeywords.add(keyword + "背景");
            relatedKeywords.add(keyword + "可爱");
            relatedKeywords.add(keyword + "高清");
            relatedKeywords.add(keyword + "风格");
        }
        return new SearchQueryPlan(
                new ArrayList<>(searchKeywords).stream().limit(18).toList(),
                new ArrayList<>(relatedKeywords).stream().filter(item -> !item.equalsIgnoreCase(keyword)).limit(RELATED_LIMIT).toList()
        );
    }

    private List<ApiDtos.SearchSuggestionItem> relatedItems(SearchQueryPlan plan, List<SearchSuggestionEntity> rows) {
        LinkedHashSet<String> seen = new LinkedHashSet<>();
        List<ApiDtos.SearchSuggestionItem> items = new ArrayList<>();
        for (String keyword : plan.relatedKeywords()) {
            if (seen.add(keyword.toLowerCase(Locale.ROOT))) {
                items.add(new ApiDtos.SearchSuggestionItem(keyword, "intent", null, null));
            }
        }
        for (SearchSuggestionEntity row : rows) {
            String keyword = normalize(row.getKeyword());
            if (!StringUtils.hasText(keyword)) continue;
            if (seen.add(keyword.toLowerCase(Locale.ROOT))) {
                items.add(new ApiDtos.SearchSuggestionItem(keyword, row.getKind(), row.getImageUrl(), row.getPostCount()));
            }
            if (items.size() >= RELATED_LIMIT) break;
        }
        return items.stream().limit(RELATED_LIMIT).toList();
    }

    private List<ApiDtos.SearchSuggestionItem> toSuggestionItems(List<SearchSuggestionEntity> rows) {
        return rows.stream()
                .map(row -> new ApiDtos.SearchSuggestionItem(row.getKeyword(), row.getKind(), row.getImageUrl(), row.getPostCount()))
                .toList();
    }

    private String normalize(String value) {
        return value == null ? "" : value.trim();
    }

    private record SearchQueryPlan(List<String> searchKeywords, List<String> relatedKeywords) {
    }

    private record IntentRule(List<String> triggers, List<String> expansions, List<String> related) {
        private boolean matches(String query) {
            for (String trigger : triggers) {
                String normalized = trigger.toLowerCase(Locale.ROOT);
                if (query.contains(normalized) || normalized.contains(query)) return true;
            }
            return false;
        }
    }
}
