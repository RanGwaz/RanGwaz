package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.api.PageResponse;
import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.CommentEntity;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.CommentMapper;
import com.rangwaz.imagesite.mapper.FollowMapper;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import com.rangwaz.imagesite.mapper.InteractionMapper;
import com.rangwaz.imagesite.mapper.UserMapper;
import com.rangwaz.imagesite.service.InteractionService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.List;

/**
 * Default interaction service implementation.
 */
@Service
public class InteractionServiceImpl implements InteractionService {
    private static final String LIKE = "LIKE";
    private static final String FAVORITE = "FAVORITE";
    private final InteractionMapper interactionMapper;
    private final CommentMapper commentMapper;
    private final FollowMapper followMapper;
    private final ImageContentMapper imageContentMapper;
    private final UserMapper userMapper;
    private final UserServiceImpl userService;
    private final ImageServiceImpl imageService;

    /**
     * Creates the interaction service.
     *
     * @param interactionMapper interaction mapper
     * @param commentMapper comment mapper
     * @param followMapper follow mapper
     * @param imageContentMapper image content mapper
     * @param userMapper user mapper
     * @param userService user service
     * @param imageService post service
     */
    public InteractionServiceImpl(InteractionMapper interactionMapper,
                                  CommentMapper commentMapper,
                                  FollowMapper followMapper,
                                  ImageContentMapper imageContentMapper,
                                  UserMapper userMapper,
                                  UserServiceImpl userService,
                                  ImageServiceImpl imageService) {
        this.interactionMapper = interactionMapper;
        this.commentMapper = commentMapper;
        this.followMapper = followMapper;
        this.imageContentMapper = imageContentMapper;
        this.userMapper = userMapper;
        this.userService = userService;
        this.imageService = imageService;
    }

    /**
     * Toggles a like.
     *
     * @param userId user id
     * @param postId post id
     * @param latitude optional latitude
     * @param longitude optional longitude
     * @param locationLabel optional human-readable location
     * @return toggle result
     */
    @Override
    @Transactional
    public ApiDtos.ToggleResult toggleLike(Long userId, Long postId, Double latitude, Double longitude, String locationLabel) {
        imageService.requirePost(postId);
        boolean active = interactionMapper.countActive(userId, postId, LIKE) == 0;
        interactionMapper.upsert(userId, postId, LIKE, active);
        imageContentMapper.changeLike(postId, active ? 1 : -1);
        imageService.trackBehavior(userId, null, postId, active ? "like" : "unlike", "interaction", null, null, cleanCoordinate(latitude), cleanCoordinate(longitude), cleanLocationLabel(locationLabel));
        return new ApiDtos.ToggleResult(active);
    }

    /**
     * Toggles a favorite.
     *
     * @param userId user id
     * @param postId post id
     * @param latitude optional latitude
     * @param longitude optional longitude
     * @param locationLabel optional human-readable location
     * @return toggle result
     */
    @Override
    @Transactional
    public ApiDtos.ToggleResult toggleFavorite(Long userId, Long postId, Double latitude, Double longitude, String locationLabel) {
        imageService.requirePost(postId);
        boolean active = interactionMapper.countActive(userId, postId, FAVORITE) == 0;
        interactionMapper.upsert(userId, postId, FAVORITE, active);
        imageContentMapper.changeFavorite(postId, active ? 1 : -1);
        imageService.trackBehavior(userId, null, postId, active ? "favorite" : "unfavorite", "interaction", null, null, cleanCoordinate(latitude), cleanCoordinate(longitude), cleanLocationLabel(locationLabel));
        return new ApiDtos.ToggleResult(active);
    }

    /**
     * Gets current user's interaction status.
     *
     * @param userId user id
     * @param postId post id
     * @return status response
     */
    @Override
    public ApiDtos.ImageInteractionStatus status(Long userId, Long postId) {
        return new ApiDtos.ImageInteractionStatus(
                interactionMapper.countActive(userId, postId, LIKE) > 0,
                interactionMapper.countActive(userId, postId, FAVORITE) > 0
        );
    }

    /**
     * Lists images liked by a user.
     *
     * @param userId user id
     * @param limit maximum rows
     * @return liked images
     */
    @Override
    public List<ApiDtos.ImageView> likedImages(Long userId, int limit) {
        if (userMapper.findById(userId) == null) throw new BusinessException("USER_NOT_FOUND", "用户不存在");
        int safeLimit = Math.max(1, Math.min(limit, 100));
        return imageService.toViews(interactionMapper.findActiveImages(userId, LIKE, safeLimit), "liked");
    }

    @Override
    public List<ApiDtos.ImageView> favoriteImages(Long userId, int limit) {
        if (userMapper.findById(userId) == null) throw new BusinessException("USER_NOT_FOUND", "用户不存在");
        int safeLimit = Math.max(1, Math.min(limit, 100));
        return imageService.toViews(interactionMapper.findActiveImages(userId, FAVORITE, safeLimit), "favorites");
    }

    @Override
    public List<ApiDtos.UserSummary> following(Long userId, int limit) {
        if (userMapper.findById(userId) == null) throw new BusinessException("USER_NOT_FOUND", "用户不存在");
        int safeLimit = Math.max(1, Math.min(limit, 100));
        return followMapper.findFollowing(userId, safeLimit).stream()
                .map(userService::toSummary)
                .toList();
    }

    @Override
    public List<ApiDtos.UserSummary> followers(Long userId, int limit) {
        if (userMapper.findById(userId) == null) throw new BusinessException("USER_NOT_FOUND", "用户不存在");
        int safeLimit = Math.max(1, Math.min(limit, 100));
        return followMapper.findFollowers(userId, safeLimit).stream()
                .map(userService::toSummary)
                .toList();
    }

    /**
     * Pages comments.
     *
     * @param postId post id
     * @param page page number
     * @param size page size
     * @return comment page
     */
    @Override
    public PageResponse<ApiDtos.CommentView> comments(Long postId, int page, int size) {
        imageService.requirePost(postId);
        int safePage = Math.max(1, page);
        int safeSize = Math.max(1, Math.min(size, 80));
        int offset = (safePage - 1) * safeSize;
        var records = commentMapper.pageByImageId(postId, offset, safeSize).stream().map(this::toView).toList();
        return new PageResponse<>(records, commentMapper.countByImageId(postId), safePage, safeSize);
    }

    /**
     * Creates a comment.
     *
     * @param userId author id
     * @param postId post id
     * @param request creation request
     * @return created comment
     */
    @Override
    @Transactional
    public ApiDtos.CommentView comment(Long userId, Long postId, ApiDtos.CreateCommentRequest request) {
        imageService.requirePost(postId);
        CommentEntity comment = new CommentEntity();
        comment.setAuthorId(userId);
        comment.setImageId(postId);
        comment.setParentCommentId(request.parentCommentId());
        comment.setContent(request.content().trim());
        comment.setStatus("VISIBLE");
        commentMapper.insert(comment);
        imageContentMapper.changeComment(postId, 1);
        imageService.trackBehavior(userId, null, postId, "comment", "detail", null, null);
        return toView(commentMapper.findById(comment.getId()));
    }

    /**
     * Follows a user.
     *
     * @param followerId follower id
     * @param followeeId followee id
     * @param scene scene
     */
    @Override
    public void follow(Long followerId, Long followeeId, String scene) {
        if (followerId.equals(followeeId)) throw new BusinessException("FOLLOW_SELF", "不能关注自己");
        if (userMapper.findById(followeeId) == null) throw new BusinessException("USER_NOT_FOUND", "用户不存在");
        followMapper.follow(followerId, followeeId, StringUtils.hasText(scene) ? scene : "unknown");
    }

    /**
     * Unfollows a user.
     *
     * @param followerId follower id
     * @param followeeId followee id
     */
    @Override
    public void unfollow(Long followerId, Long followeeId) {
        followMapper.unfollow(followerId, followeeId);
    }

    /**
     * Gets follow status.
     *
     * @param followerId follower id
     * @param followeeId followee id
     * @return status response
     */
    @Override
    public ApiDtos.FollowStatus followStatus(Long followerId, Long followeeId) {
        return new ApiDtos.FollowStatus(followerId != null && followMapper.exists(followerId, followeeId) > 0);
    }

    /**
     * Tracks a behavior event.
     *
     * @param userId optional user id
     * @param request behavior request
     */
    @Override
    public void behavior(Long userId, String visitorId, ApiDtos.BehaviorRequest request) {
        if (request == null) throw new BusinessException("IMAGE_REQUIRED", "image is required");
        if (request.imageId() == null) throw new BusinessException("IMAGE_REQUIRED", "缺少图片内容");
        String type = StringUtils.hasText(request.behaviorType()) ? request.behaviorType().trim() : "unknown";
        String scene = StringUtils.hasText(request.scene()) ? request.scene().trim() : "unknown";
        imageService.trackBehavior(
                userId,
                cleanVisitorId(firstText(request.visitorId(), visitorId)),
                request.imageId(),
                type,
                scene,
                request.position(),
                request.duration(),
                cleanCoordinate(request.latitude()),
                cleanCoordinate(request.longitude()),
                cleanLocationLabel(request.locationLabel())
        );
    }

    /**
     * Tracks multiple behavior events.
     *
     * @param userId optional user id
     * @param request batch behavior request
     */
    @Override
    public void behaviors(Long userId, String visitorId, ApiDtos.BehaviorBatchRequest request) {
        if (request == null || request.events() == null) return;
        String batchVisitorId = cleanVisitorId(firstText(visitorId, request.visitorId()));
        request.events().stream()
                .filter(event -> event != null && event.imageId() != null)
                .limit(100)
                .forEach(event -> behavior(userId, batchVisitorId, event));
    }

    private String firstText(String first, String second) {
        if (StringUtils.hasText(first)) return first;
        return second;
    }

    private String cleanVisitorId(String visitorId) {
        if (!StringUtils.hasText(visitorId)) return null;
        String cleaned = visitorId.trim();
        return cleaned.length() > 64 ? cleaned.substring(0, 64) : cleaned;
    }

    private Double cleanCoordinate(Double value) {
        if (value == null || !Double.isFinite(value)) return null;
        return value;
    }

    private String cleanLocationLabel(String value) {
        if (!StringUtils.hasText(value)) return null;
        String cleaned = value.trim();
        return cleaned.length() > 80 ? cleaned.substring(0, 80) : cleaned;
    }

    private ApiDtos.CommentView toView(CommentEntity comment) {
        UserEntity author = userMapper.findById(comment.getAuthorId());
        ApiDtos.UserSummary replyTo = null;
        if (comment.getParentCommentId() != null) {
            CommentEntity parent = commentMapper.findById(comment.getParentCommentId());
            if (parent != null) replyTo = userService.findSummary(parent.getAuthorId());
        }
        return new ApiDtos.CommentView(
                comment.getId(),
                userService.toSummary(author),
                comment.getParentCommentId(),
                replyTo,
                comment.getContent(),
                comment.getCreatedAt()
        );
    }
}
