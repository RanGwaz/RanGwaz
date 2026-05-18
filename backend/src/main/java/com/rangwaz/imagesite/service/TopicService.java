package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.TopicEntity;

import java.util.List;

/**
 * Service interface for topics.
 */
public interface TopicService {
    /**
     * Lists trending topics.
     *
     * @param limit maximum rows
     * @return topics
     */
    List<ApiDtos.TopicView> trending(int limit);

    /**
     * Searches topics.
     *
     * @param keyword keyword
     * @param limit maximum rows
     * @return topics
     */
    List<ApiDtos.TopicView> search(String keyword, int limit);

    /**
     * Gets or creates a topic by name.
     *
     * @param name topic name
     * @return topic entity
     */
    TopicEntity getOrCreate(String name);
}
