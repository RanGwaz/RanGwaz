package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.CategoryEntity;
import com.rangwaz.imagesite.entity.ImageEntity;
import com.rangwaz.imagesite.entity.TagEntity;
import com.rangwaz.imagesite.mapper.CategoryMapper;
import com.rangwaz.imagesite.mapper.ImageMapper;
import com.rangwaz.imagesite.mapper.TagMapper;
import com.rangwaz.imagesite.service.ImageMetadataService;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Reads image metadata without seeding or guessing taxonomy.
 */
@Service
public class ImageMetadataServiceImpl implements ImageMetadataService {
    private final CategoryMapper categoryMapper;
    private final TagMapper tagMapper;
    private final ImageMapper imageMapper;

    /**
     * Creates the image metadata service.
     *
     * @param categoryMapper category mapper
     * @param tagMapper tag mapper
     * @param imageMapper image mapper
     */
    public ImageMetadataServiceImpl(CategoryMapper categoryMapper, TagMapper tagMapper, ImageMapper imageMapper) {
        this.categoryMapper = categoryMapper;
        this.tagMapper = tagMapper;
        this.imageMapper = imageMapper;
    }

    /**
     * Reads metadata by image id.
     *
     * @param imageId image id
     * @return image metadata view
     */
    @Override
    public ApiDtos.ImageMetadataView findByImageId(Long imageId) {
        if (imageId == null) return null;
        return toImageMetadataView(imageMapper.findById(imageId));
    }

    /**
     * Lists category tree from stored taxonomy rows only.
     *
     * @return category tree
     */
    @Override
    public List<ApiDtos.CategoryView> categoryTree() {
        List<CategoryEntity> all = categoryMapper.findAll();
        Map<Long, CategoryNode> nodes = new LinkedHashMap<>();
        for (CategoryEntity category : all) {
            nodes.put(category.getId(), new CategoryNode(category));
        }
        List<CategoryNode> roots = new ArrayList<>();
        for (CategoryNode node : nodes.values()) {
            if (node.category().getParentId() == null) {
                roots.add(node);
            } else {
                CategoryNode parent = nodes.get(node.category().getParentId());
                if (parent == null) roots.add(node);
                else parent.children().add(node);
            }
        }
        return roots.stream()
                .sorted(categoryComparator())
                .map(this::toCategoryView)
                .toList();
    }

    /**
     * Lists tags from stored taxonomy rows only.
     *
     * @param type optional tag type
     * @param limit maximum rows
     * @return tags
     */
    @Override
    public List<ApiDtos.TagView> tags(String type, int limit) {
        String normalizedType = StringUtils.hasText(type) ? type.trim() : null;
        List<TagEntity> tagEntities = normalizedType == null
                ? tagMapper.findAll(Math.max(1, Math.min(limit, 500)))
                : tagMapper.findByType(normalizedType, Math.max(1, Math.min(limit, 500)));
        return tagEntities
                .stream()
                .map(this::toTagView)
                .toList();
    }

    /**
     * Converts image metadata to a view.
     *
     * @param image image entity
     * @return view
     */
    public ApiDtos.ImageMetadataView toImageMetadataView(ImageEntity image) {
        if (image == null) return null;
        CategoryEntity category = imageMapper.findCategoryByImageId(image.getId());
        List<ApiDtos.ImageTagView> tags = imageMapper.findTagRowsByImageId(image.getId())
                .stream()
                .map(row -> new ApiDtos.ImageTagView(
                        row.getId(),
                        row.getName(),
                        row.getType(),
                        row.getSlug(),
                        row.getConfidence() == null ? 1d : row.getConfidence().doubleValue(),
                        row.getSource()
                ))
                .toList();
        return new ApiDtos.ImageMetadataView(
                image.getId(),
                image.getId(),
                category == null ? null : toCategoryView(new CategoryNode(category)),
                image.getRatio(),
                image.getFileSize(),
                image.getHash(),
                tags
        );
    }

    private ApiDtos.CategoryView toCategoryView(CategoryNode node) {
        CategoryEntity category = node.category();
        List<ApiDtos.CategoryView> children = node.children().stream()
                .sorted(categoryComparator())
                .map(this::toCategoryView)
                .toList();
        return new ApiDtos.CategoryView(
                category.getId(),
                category.getName(),
                category.getParentId(),
                category.getSlug(),
                category.getSortNo(),
                children
        );
    }

    private ApiDtos.TagView toTagView(TagEntity tag) {
        return new ApiDtos.TagView(tag.getId(), tag.getName(), tag.getType(), tag.getSlug());
    }

    private Comparator<CategoryNode> categoryComparator() {
        return Comparator
                .comparing((CategoryNode node) -> node.category().getSortNo() == null ? 0 : node.category().getSortNo())
                .thenComparing(node -> node.category().getId() == null ? 0L : node.category().getId());
    }

    private record CategoryNode(CategoryEntity category, List<CategoryNode> children) {
        private CategoryNode(CategoryEntity category) {
            this(category, new ArrayList<>());
        }
    }
}
