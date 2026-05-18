package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.dto.ApiDtos;

/**
 * Service interface for global search.
 */
public interface SearchService {
    /**
     * Searches posts, users, and topics.
     *
     * @param keyword keyword
     * @return search result
     */
    ApiDtos.SearchResult search(String keyword);
}
