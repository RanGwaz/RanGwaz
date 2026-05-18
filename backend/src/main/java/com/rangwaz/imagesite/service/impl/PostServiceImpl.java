package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.PostAssetEntity;
import com.rangwaz.imagesite.entity.PostEntity;
import com.rangwaz.imagesite.entity.TopicEntity;
import com.rangwaz.imagesite.entity.UserBehaviorEntity;
import com.rangwaz.imagesite.mapper.BehaviorMapper;
import com.rangwaz.imagesite.mapper.PostAssetMapper;
import com.rangwaz.imagesite.mapper.PostMapper;
import com.rangwaz.imagesite.mapper.TopicMapper;
import com.rangwaz.imagesite.service.PostService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.CollectionUtils;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;

/**
 * Default post service implementation.
 */
@Service
public class PostServiceImpl implements PostService {
    private final PostMapper postMapper;
    private final PostAssetMapper postAssetMapper;
    private final TopicMapper topicMapper;
    private final BehaviorMapper behaviorMapper;
    private final UserServiceImpl userService;
    private final TopicServiceImpl topicService;

    /**
     * Creates the post service.
     *
     * @param postMapper post mapper
     * @param postAssetMapper post asset mapper
     * @param topicMapper topic mapper
     * @param behaviorMapper behavior mapper
     * @param userService user service
     * @param topicService topic service
     */
    public PostServiceImpl(PostMapper postMapper,
                           PostAssetMapper postAssetMapper,
                           TopicMapper topicMapper,
                           BehaviorMapper behaviorMapper,
                           UserServiceImpl userService,
                           TopicServiceImpl topicService) {
        this.postMapper = postMapper;
        this.postAssetMapper = postAssetMapper;
        this.topicMapper = topicMapper;
        this.behaviorMapper = behaviorMapper;
        this.userService = userService;
        this.topicService = topicService;
    }

    /**
     * Creates a post.
     *
     * @param authorId author id
     * @param request creation request
     * @return created post view
     */
    @Override
    @Transactional
    public ApiDtos.PostView create(Long authorId, ApiDtos.CreatePostRequest request) {
        List<ApiDtos.PostAssetRequest> assets = normalizeAssets(request);
        String coverUrl = assets.isEmpty() ? null : assets.get(0).fileUrl();
        PostEntity post = new PostEntity();
        post.setAuthorId(authorId);
        post.setTitle(request.title().trim());
        post.setContent(StringUtils.hasText(request.content()) ? request.content().trim() : "");
        post.setCoverUrl(coverUrl);
        post.setThumbUrl(assets.isEmpty() ? null : assets.get(0).thumbUrl());
        post.setPostType(StringUtils.hasText(request.postType()) ? request.postType() : "image");
        post.setStatus("PUBLISHED");
        post.setLikeCount(0);
        post.setFavoriteCount(0);
        post.setCommentCount(0);
        post.setShareCount(0);
        post.setViewCount(0);
        post.setHotScore(BigDecimal.valueOf(12));
        post.setPublishedAt(LocalDateTime.now());
        postMapper.insert(post);
        for (int i = 0; i < assets.size(); i++) {
            postAssetMapper.insert(toAssetEntity(post.getId(), assets.get(i), i));
        }
        for (String topicName : uniqueTopics(request)) {
            TopicEntity topic = topicService.getOrCreate(topicName);
            if (topic == null) continue;
            topicMapper.bindPost(post.getId(), topic.getId());
            topicMapper.incrementPostCount(topic.getId());
        }
        return toView(postMapper.findById(post.getId()), "已发布");
    }

    /**
     * Gets a post detail.
     *
     * @param postId post id
     * @param viewerId optional viewer id
     * @return post view
     */
    @Override
    public ApiDtos.PostView detail(Long postId, Long viewerId) {
        PostEntity post = requirePost(postId);
        postMapper.incrementView(postId);
        if (viewerId != null) {
            trackBehavior(viewerId, postId, "view", "detail", null, null);
        }
        return toView(postMapper.findById(postId), "与你最近浏览的图片风格相近");
    }

    /**
     * Lists posts authored by a user.
     *
     * @param userId author id
     * @param limit maximum rows
     * @return post views
     */
    @Override
    public List<ApiDtos.PostView> byUser(Long userId, int limit) {
        return postMapper.findByAuthor(userId, Math.max(1, Math.min(limit, 200))).stream()
                .map(post -> toView(post, null))
                .toList();
    }

    /**
     * Tracks a post click.
     *
     * @param postId post id
     * @param viewerId optional viewer id
     * @param scene scene
     * @param position position
     */
    @Override
    public void click(Long postId, Long viewerId, String scene, Integer position) {
        requirePost(postId);
        postMapper.incrementView(postId);
        trackBehavior(viewerId, postId, "click", scene, position, null);
    }

    /**
     * Tracks a share.
     *
     * @param postId post id
     */
    @Override
    public void share(Long postId) {
        requirePost(postId);
        postMapper.incrementShare(postId);
    }

    /**
     * Converts a post entity to a frontend view.
     *
     * @param post post entity
     * @param reason recommendation reason
     * @return post view
     */
    public ApiDtos.PostView toView(PostEntity post, String reason) {
        if (post == null) return null;
        List<PostAssetEntity> assets = postAssetMapper.findByPostId(post.getId());
        List<ApiDtos.PostAssetView> assetViews = assets.stream().map(this::toAssetView).toList();
        List<ApiDtos.PostImageView> images = assetViews.stream()
                .map(asset -> new ApiDtos.PostImageView(asset.fileUrl(), asset.width(), asset.height()))
                .toList();
        List<String> tags = topicMapper.findByPostId(post.getId()).stream().map(TopicEntity::getName).toList();
        String coverUrl = StringUtils.hasText(post.getCoverUrl())
                ? post.getCoverUrl()
                : assetViews.stream().findFirst().map(ApiDtos.PostAssetView::fileUrl).orElse(null);
        return new ApiDtos.PostView(
                post.getId(),
                userService.findSummary(post.getAuthorId()),
                post.getTitle(),
                post.getContent(),
                tags,
                tags.isEmpty() ? "推荐" : tags.get(0),
                tags.isEmpty() ? "recommend" : tags.get(0),
                post.getPostType(),
                assetViews,
                images,
                coverUrl,
                StringUtils.hasText(post.getThumbUrl()) ? post.getThumbUrl() : coverUrl,
                post.getLikeCount(),
                post.getFavoriteCount(),
                post.getFavoriteCount(),
                post.getCommentCount(),
                post.getShareCount(),
                post.getViewCount(),
                reason,
                post.getPublishedAt()
        );
    }

    /**
     * Requires a published post.
     *
     * @param postId post id
     * @return post entity
     */
    public PostEntity requirePost(Long postId) {
        PostEntity post = postMapper.findById(postId);
        if (post == null) throw new BusinessException("POST_NOT_FOUND", "图片内容不存在");
        return post;
    }

    /**
     * Tracks a recommendation behavior event.
     *
     * @param userId optional user id
     * @param postId post id
     * @param type behavior type
     * @param scene scene
     * @param position position
     * @param duration duration
     */
    public void trackBehavior(Long userId, Long postId, String type, String scene, Integer position, Integer duration) {
        UserBehaviorEntity behavior = new UserBehaviorEntity();
        behavior.setUserId(userId);
        behavior.setPostId(postId);
        behavior.setBehaviorType(StringUtils.hasText(type) ? type : "unknown");
        behavior.setScene(StringUtils.hasText(scene) ? scene : "unknown");
        behavior.setPositionNo(position);
        behavior.setDurationMs(duration);
        behaviorMapper.insert(behavior);
    }

    /**
     * Converts an asset entity to a view.
     *
     * @param asset asset entity
     * @return asset view
     */
    private ApiDtos.PostAssetView toAssetView(PostAssetEntity asset) {
        return new ApiDtos.PostAssetView(
                asset.getId(),
                asset.getObjectKey(),
                asset.getFileUrl(),
                asset.getFileType(),
                asset.getThumbUrl(),
                asset.getWidth(),
                asset.getHeight(),
                asset.getSortOrder()
        );
    }

    /**
     * Converts a request asset to an entity.
     *
     * @param postId post id
     * @param request asset request
     * @param fallbackOrder fallback sort order
     * @return asset entity
     */
    private PostAssetEntity toAssetEntity(Long postId, ApiDtos.PostAssetRequest request, int fallbackOrder) {
        PostAssetEntity asset = new PostAssetEntity();
        asset.setPostId(postId);
        asset.setObjectKey(StringUtils.hasText(request.objectKey()) ? request.objectKey() : "remote-" + Math.abs(request.fileUrl().hashCode()));
        asset.setFileUrl(request.fileUrl());
        asset.setFileType(StringUtils.hasText(request.fileType()) ? request.fileType() : "image");
        asset.setThumbUrl(StringUtils.hasText(request.thumbUrl()) ? request.thumbUrl() : request.fileUrl());
        asset.setWidth(request.width());
        asset.setHeight(request.height());
        asset.setSortOrder(request.sortOrder() == null ? fallbackOrder : request.sortOrder());
        return asset;
    }

    /**
     * Normalizes asset payloads and image URLs.
     *
     * @param request post creation request
     * @return asset requests
     */
    private List<ApiDtos.PostAssetRequest> normalizeAssets(ApiDtos.CreatePostRequest request) {
        List<ApiDtos.PostAssetRequest> assets = new ArrayList<>();
        if (!CollectionUtils.isEmpty(request.assets())) {
            assets.addAll(request.assets().stream()
                    .filter(asset -> StringUtils.hasText(asset.fileUrl()))
                    .toList());
        }
        if (assets.isEmpty() && !CollectionUtils.isEmpty(request.imageUrls())) {
            for (int i = 0; i < request.imageUrls().size(); i++) {
                String url = request.imageUrls().get(i);
                if (!StringUtils.hasText(url)) continue;
                assets.add(new ApiDtos.PostAssetRequest("remote-" + Math.abs(url.hashCode()), url, "image", url, null, null, i));
            }
        }
        return assets;
    }

    /**
     * Builds a unique topic list from tags and topics.
     *
     * @param request post creation request
     * @return topic names
     */
    private List<String> uniqueTopics(ApiDtos.CreatePostRequest request) {
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
