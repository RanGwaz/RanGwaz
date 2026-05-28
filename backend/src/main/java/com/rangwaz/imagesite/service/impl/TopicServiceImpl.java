package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.TopicEntity;
import com.rangwaz.imagesite.mapper.TopicMapper;
import com.rangwaz.imagesite.service.TopicService;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.text.Normalizer;
import java.util.List;
import java.util.Locale;

/**
 * Default topic service implementation.
 */
@Service
public class TopicServiceImpl implements TopicService {
    private final TopicMapper topicMapper;

    /**
     * Creates the topic service.
     *
     * @param topicMapper topic mapper
     */
    public TopicServiceImpl(TopicMapper topicMapper) {
        this.topicMapper = topicMapper;
    }

    /**
     * Lists trending topics.
     *
     * @param limit maximum rows
     * @return topics
     */
    @Override
    public List<ApiDtos.TopicView> trending(int limit) {
        return topicMapper.trending(Math.max(1, Math.min(limit, 50))).stream().map(this::toView).toList();
    }

    /**
     * Searches topics.
     *
     * @param keyword keyword
     * @param limit maximum rows
     * @return topics
     */
    @Override
    public List<ApiDtos.TopicView> search(String keyword, int limit) {
        String normalized = normalizeName(keyword);
        if (!StringUtils.hasText(normalized)) return trending(limit);
        return topicMapper.search(normalized, Math.max(1, Math.min(limit, 50))).stream().map(this::toView).toList();
    }

    /**
     * Gets or creates a topic by name.
     *
     * @param name topic name
     * @return topic entity
     */
    @Override
    public TopicEntity getOrCreate(String name) {
        String normalized = normalizeName(name);
        if (!StringUtils.hasText(normalized)) return null;
        TopicEntity existing = topicMapper.findByName(normalized);
        if (existing != null) return existing;
        TopicEntity topic = new TopicEntity();
        topic.setName(normalized);
        topic.setSlug(slug(normalized));
        topic.setDescription("");
        topic.setCoverUrl(null);
        topic.setPostCount(0);
        topic.setFollowerCount(0);
        topic.setHotScore(BigDecimal.ZERO);
        topicMapper.insert(topic);
        return topic;
    }

    /**
     * Converts a topic entity into a view.
     *
     * @param topic topic entity
     * @return topic view
     */
    public ApiDtos.TopicView toView(TopicEntity topic) {
        return new ApiDtos.TopicView(
                topic.getId(),
                topic.getName(),
                topic.getSlug(),
                topic.getDescription(),
                topic.getCoverUrl(),
                topic.getPostCount(),
                topic.getFollowerCount(),
                topic.getHotScore() == null ? 0d : topic.getHotScore().doubleValue()
        );
    }

    /**
     * Normalizes topic names.
     *
     * @param raw raw topic name
     * @return normalized name
     */
    private String normalizeName(String raw) {
        return raw == null ? "" : raw.trim().replaceFirst("^#+", "").replaceAll("\\s+", "");
    }

    /**
     * Creates a stable slug.
     *
     * @param name topic name
     * @return slug
     */
    private String slug(String name) {
        String ascii = Normalizer.normalize(name, Normalizer.Form.NFD)
                .replaceAll("[^\\p{ASCII}]", "")
                .replaceAll("[^A-Za-z0-9]+", "-")
                .replaceAll("^-|-$", "")
                .toLowerCase(Locale.ROOT);
        if (StringUtils.hasText(ascii)) return ascii;
        return "topic-" + Math.abs(name.hashCode());
    }
}
