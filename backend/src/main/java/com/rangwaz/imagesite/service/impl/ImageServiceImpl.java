package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.ImageEntity;
import com.rangwaz.imagesite.entity.TopicEntity;
import com.rangwaz.imagesite.entity.UserBehaviorEntity;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.BehaviorMapper;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import com.rangwaz.imagesite.mapper.TopicMapper;
import com.rangwaz.imagesite.mapper.UserMapper;
import com.rangwaz.imagesite.service.ImageMetadataService;
import com.rangwaz.imagesite.service.ImageService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.CollectionUtils;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * Post API service backed by the canonical images table.
 */
@Service
public class ImageServiceImpl implements ImageService {
    private final ImageContentMapper imageContentMapper;
    private final TopicMapper topicMapper;
    private final UserMapper userMapper;
    private final BehaviorMapper behaviorMapper;
    private final UserServiceImpl userService;
    private final TopicServiceImpl topicService;
    private final ImageMetadataService imageMetadataService;

    /**
     * Creates the post service.
     *
     * @param imageContentMapper image content mapper
     * @param topicMapper topic mapper
     * @param userMapper user mapper
     * @param behaviorMapper behavior mapper
     * @param userService user service
     * @param topicService topic service
     * @param imageMetadataService image metadata service
     */
    public ImageServiceImpl(ImageContentMapper imageContentMapper,
                           TopicMapper topicMapper,
                           UserMapper userMapper,
                           BehaviorMapper behaviorMapper,
                           UserServiceImpl userService,
                           TopicServiceImpl topicService,
                           ImageMetadataService imageMetadataService) {
        this.imageContentMapper = imageContentMapper;
        this.topicMapper = topicMapper;
        this.userMapper = userMapper;
        this.behaviorMapper = behaviorMapper;
        this.userService = userService;
        this.topicService = topicService;
        this.imageMetadataService = imageMetadataService;
    }

    /**
     * Creates an image content row.
     *
     * @param authorId author id
     * @param request creation request
     * @return created post-compatible view
     */
    @Override
    @Transactional
    public ApiDtos.ImageView create(Long authorId, ApiDtos.CreateImageRequest request) {
        List<ApiDtos.ImageAssetRequest> assets = normalizeAssets(request);
        if (assets.isEmpty()) throw new BusinessException("IMAGE_REQUIRED", "image required");
        ImageEntity image = toImageEntity(authorId, request, assets.get(0));
        imageContentMapper.insert(image);

        for (String topicName : uniqueTopics(request)) {
            TopicEntity topic = topicService.getOrCreate(topicName);
            if (topic == null) continue;
            topicMapper.bindImage(image.getId(), topic.getId());
            topicMapper.incrementPostCount(topic.getId());
        }
        return toView(imageContentMapper.findById(image.getId()), "published");
    }

    /**
     * Gets image content detail.
     *
     * @param postId image id exposed as post id
     * @param viewerId optional viewer id
     * @return post-compatible view
     */
    @Override
    public ApiDtos.ImageView detail(Long postId, Long viewerId) {
        requirePost(postId);
        imageContentMapper.incrementView(postId);
        if (viewerId != null) {
            trackBehavior(viewerId, postId, "view", "detail", null, null);
        }
        return toView(imageContentMapper.findById(postId), "detail");
    }

    /**
     * Lists image content authored by a user.
     *
     * @param userId author id
     * @param limit maximum rows
     * @return post-compatible views
     */
    @Override
    public List<ApiDtos.ImageView> byUser(Long userId, int limit) {
        return toViews(imageContentMapper.findByAuthor(userId, Math.max(1, Math.min(limit, 200))), null);
    }

    /**
     * Tracks an image content click.
     *
     * @param postId image id exposed as post id
     * @param viewerId optional user id
     * @param scene scene
     * @param position position
     */
    @Override
    public void click(Long postId, Long viewerId, String scene, Integer position) {
        requirePost(postId);
        imageContentMapper.incrementView(postId);
        trackBehavior(viewerId, postId, "click", scene, position, null);
    }

    /**
     * Tracks a share.
     *
     * @param postId image id exposed as post id
     */
    @Override
    public void share(Long postId) {
        requirePost(postId);
        imageContentMapper.incrementShare(postId);
    }

    /**
     * Converts one image content row to a frontend post-compatible view.
     *
     * @param image image content row
     * @param reason recommendation reason
     * @return post-compatible view
     */
    public ApiDtos.ImageView toView(ImageEntity image, String reason) {
        if (image == null) return null;
        List<String> tags = topicMapper.findByImageId(image.getId()).stream().map(TopicEntity::getName).toList();
        return toView(image, reason, tags, userService.findSummary(image.getAuthorId()), true);
    }

    /**
     * Converts image content rows using batch-loaded associations.
     *
     * @param images image content rows
     * @param reason recommendation reason
     * @return post-compatible views
     */
    public List<ApiDtos.ImageView> toViews(List<ImageEntity> images, String reason) {
        return toViews(images, reason, false);
    }

    /**
     * Converts image content rows using batch-loaded associations.
     *
     * @param images image content rows
     * @param reason recommendation reason
     * @param includeMetadata whether each image should include tag/category metadata
     * @return post-compatible views
     */
    public List<ApiDtos.ImageView> toViews(List<ImageEntity> images, String reason, boolean includeMetadata) {
        if (CollectionUtils.isEmpty(images)) return List.of();
        List<Long> imageIds = images.stream()
                .map(ImageEntity::getId)
                .filter(Objects::nonNull)
                .distinct()
                .toList();
        Map<Long, List<String>> topicsByImageId = imageIds.isEmpty()
                ? Map.of()
                : topicMapper.findRowsByImageIds(imageIds).stream()
                .collect(Collectors.groupingBy(
                        TopicMapper.ImageTopicRow::getImageId,
                        LinkedHashMap::new,
                        Collectors.mapping(TopicMapper.ImageTopicRow::getName, Collectors.toList())
                ));
        List<Long> authorIds = images.stream()
                .map(ImageEntity::getAuthorId)
                .filter(Objects::nonNull)
                .distinct()
                .toList();
        Map<Long, ApiDtos.UserSummary> authorsById = authorIds.isEmpty()
                ? Map.of()
                : userMapper.findByIds(authorIds).stream()
                .collect(Collectors.toMap(UserEntity::getId, userService::toSummary, (left, right) -> left));
        return images.stream()
                .map(image -> toView(
                        image,
                        reason,
                        topicsByImageId.getOrDefault(image.getId(), List.of()),
                        authorsById.get(image.getAuthorId()),
                        includeMetadata
                ))
                .toList();
    }

    /**
     * Requires published image content.
     *
     * @param postId image id exposed as post id
     * @return image content entity
     */
    public ImageEntity requirePost(Long postId) {
        ImageEntity image = imageContentMapper.findById(postId);
        if (image == null) throw new BusinessException("POST_NOT_FOUND", "image content not found");
        return image;
    }

    /**
     * Tracks a recommendation behavior event.
     *
     * @param userId optional user id
     * @param postId image id exposed as post id
     * @param type behavior type
     * @param scene scene
     * @param position position
     * @param duration duration
     */
    public void trackBehavior(Long userId, Long postId, String type, String scene, Integer position, Integer duration) {
        UserBehaviorEntity behavior = new UserBehaviorEntity();
        behavior.setUserId(userId);
        behavior.setImageId(postId);
        behavior.setBehaviorType(StringUtils.hasText(type) ? type : "unknown");
        behavior.setScene(StringUtils.hasText(scene) ? scene : "unknown");
        behavior.setPositionNo(position);
        behavior.setDurationMs(duration);
        behaviorMapper.insert(behavior);
    }

    private ApiDtos.ImageView toView(ImageEntity image,
                                    String reason,
                                    List<String> tags,
                                    ApiDtos.UserSummary author,
                                    boolean includeMetadata) {
        String thumbUrl = StringUtils.hasText(image.getThumbnailUrl()) ? image.getThumbnailUrl() : image.getFileUrl();
        return new ApiDtos.ImageView(
                image.getId(),
                author,
                image.getTitle(),
                image.getContent(),
                tags,
                tags.isEmpty() ? "recommend" : tags.get(0),
                tags.isEmpty() ? "recommend" : tags.get(0),
                image.getPostType(),
                List.of(toAssetView(image, includeMetadata)),
                List.of(new ApiDtos.ImageSourceView(image.getFileUrl(), image.getWidth(), image.getHeight())),
                image.getFileUrl(),
                thumbUrl,
                image.getLikeCount(),
                image.getFavoriteCount(),
                image.getFavoriteCount(),
                image.getCommentCount(),
                image.getShareCount(),
                image.getViewCount(),
                reason,
                image.getPublishedAt()
        );
    }

    private ApiDtos.ImageAssetView toAssetView(ImageEntity image, boolean includeMetadata) {
        return new ApiDtos.ImageAssetView(
                image.getId(),
                image.getObjectKey(),
                image.getFileUrl(),
                image.getFileType(),
                image.getThumbnailUrl(),
                image.getWidth(),
                image.getHeight(),
                image.getFileSize(),
                image.getHash(),
                0,
                includeMetadata ? imageMetadataService.findByImageId(image.getId()) : null
        );
    }

    private ImageEntity toImageEntity(Long authorId, ApiDtos.CreateImageRequest request, ApiDtos.ImageAssetRequest asset) {
        ImageEntity image = new ImageEntity();
        image.setAuthorId(authorId);
        image.setTitle(request.title().trim());
        image.setContent(StringUtils.hasText(request.content()) ? request.content().trim() : "");
        image.setPostType(StringUtils.hasText(request.postType()) ? request.postType() : "image");
        image.setDescription(null);
        image.setObjectKey(StringUtils.hasText(asset.objectKey()) ? asset.objectKey() : "remote-" + Math.abs(asset.fileUrl().hashCode()));
        image.setFileUrl(asset.fileUrl());
        image.setFileType(StringUtils.hasText(asset.fileType()) ? asset.fileType() : "image");
        image.setThumbnailUrl(StringUtils.hasText(asset.thumbUrl()) ? asset.thumbUrl() : asset.fileUrl());
        image.setWidth(asset.width());
        image.setHeight(asset.height());
        image.setRatio(ratioLabel(asset.width(), asset.height()));
        image.setFileSize(asset.fileSize());
        image.setHash(asset.hash());
        image.setMainCategoryId(null);
        image.setStatus("PUBLISHED");
        image.setLikeCount(0);
        image.setFavoriteCount(0);
        image.setCommentCount(0);
        image.setShareCount(0);
        image.setViewCount(0);
        image.setHotScore(BigDecimal.ZERO);
        image.setPublishedAt(LocalDateTime.now());
        return image;
    }

    private String ratioLabel(Integer width, Integer height) {
        if (width == null || height == null || width <= 0 || height <= 0) return null;
        int gcd = gcd(width, height);
        int left = width / gcd;
        int right = height / gcd;
        if (left > 80 || right > 80) {
            BigDecimal decimal = BigDecimal.valueOf((double) width / height).setScale(4, RoundingMode.HALF_UP);
            return decimal.stripTrailingZeros().toPlainString() + ":1";
        }
        return left + ":" + right;
    }

    private int gcd(int left, int right) {
        int a = Math.abs(left);
        int b = Math.abs(right);
        while (b != 0) {
            int tmp = a % b;
            a = b;
            b = tmp;
        }
        return Math.max(a, 1);
    }

    private List<ApiDtos.ImageAssetRequest> normalizeAssets(ApiDtos.CreateImageRequest request) {
        List<ApiDtos.ImageAssetRequest> assets = new ArrayList<>();
        if (!CollectionUtils.isEmpty(request.assets())) {
            assets.addAll(request.assets().stream()
                    .filter(asset -> StringUtils.hasText(asset.fileUrl()))
                    .toList());
        }
        if (assets.isEmpty() && !CollectionUtils.isEmpty(request.imageUrls())) {
            for (int i = 0; i < request.imageUrls().size(); i++) {
                String url = request.imageUrls().get(i);
                if (!StringUtils.hasText(url)) continue;
                assets.add(new ApiDtos.ImageAssetRequest("remote-" + Math.abs(url.hashCode()), url, "image", url, null, null, null, null, i));
            }
        }
        return assets;
    }

    private List<String> uniqueTopics(ApiDtos.CreateImageRequest request) {
        LinkedHashSet<String> topics = new LinkedHashSet<>();
        if (!CollectionUtils.isEmpty(request.tags())) topics.addAll(request.tags());
        if (!CollectionUtils.isEmpty(request.topics())) topics.addAll(request.topics());
        return topics.stream()
                .filter(StringUtils::hasText)
                .map(String::trim)
                .map(topic -> topic.replaceFirst("^#+", ""))
                .filter(StringUtils::hasText)
                .limit(10)
                .toList();
    }
}
