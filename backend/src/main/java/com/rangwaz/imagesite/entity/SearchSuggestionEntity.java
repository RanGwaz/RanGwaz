package com.rangwaz.imagesite.entity;

import lombok.Data;

/**
 * Lightweight search idea row composed from tags and categories.
 */
@Data
public class SearchSuggestionEntity {
    private String keyword;
    private String kind;
    private String imageUrl;
    private Long postCount;
}
