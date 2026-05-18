package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.api.PageResponse;
import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.CommentEntity;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.CommentMapper;
import com.rangwaz.imagesite.mapper.FollowMapper;
import com.rangwaz.imagesite.mapper.InteractionMapper;
import com.rangwaz.imagesite.mapper.PostMapper;
import com.rangwaz.imagesite.mapper.UserMapper;
import com.rangwaz.imagesite.service.InteractionService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

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
    private final PostMapper postMapper;
    private final UserMapper userMapper;
    private final UserServiceImpl userService;
    private final PostServiceImpl postService;

    /**
     * Creates the interaction service.
     *
     * @param interactionMapper interaction mapper
     * @param commentMapper comment mapper
     * @param followMapper follow mapper
     * @param postMapper post mapper
     * @param userMapper user mapper
     * @param userService user service
     * @param postService post service
     */
    public InteractionServiceImpl(InteractionMapper interactionMapper,
                                  CommentMapper commentMapper,
                                  FollowMapper followMapper,
                                  PostMapper postMapper,
                                  UserMapper userMapper,
                                  UserServiceImpl userService,
                                  PostServiceImpl postService) {
        this.interactionMapper = interactionMapper;
        this.commentMapper = commentMapper;
        this.followMapper = followMapper;
        this.postMapper = postMapper;
        this.userMapper = userMapper;
        this.userService = userService;
        this.postService = postService;
    }

    /**
     * Toggles a like.
     *
     * @param userId user id
     * @param postId post id
     * @return toggle result
     */
    @Override
    @Transactional
    public ApiDtos.ToggleResult toggleLike(Long userId, Long postId) {
        postService.requirePost(postId);
        boolean active = interactionMapper.countActive(userId, postId, LIKE) == 0;
        interactionMapper.upsert(userId, postId, LIKE, active);
        postMapper.changeLike(postId, active ? 1 : -1);
        postService.trackBehavior(userId, postId, active ? "like" : "unlike", "interaction", null, null);
        return new ApiDtos.ToggleResult(active);
    }

    /**
     * Toggles a favorite.
     *
     * @param userId user id
     * @param postId post id
     * @return toggle result
     */
    @Override
    @Transactional
    public ApiDtos.ToggleResult toggleFavorite(Long userId, Long postId) {
        postService.requirePost(postId);
        boolean active = interactionMapper.countActive(userId, postId, FAVORITE) == 0;
        interactionMapper.upsert(userId, postId, FAVORITE, active);
        postMapper.changeFavorite(postId, active ? 1 : -1);
        postService.trackBehavior(userId, postId, active ? "favorite" : "unfavorite", "interaction", null, null);
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
    public ApiDtos.PostInteractionStatus status(Long userId, Long postId) {
        return new ApiDtos.PostInteractionStatus(
                interactionMapper.countActive(userId, postId, LIKE) > 0,
                interactionMapper.countActive(userId, postId, FAVORITE) > 0
        );
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
        postService.requirePost(postId);
        int safePage = Math.max(1, page);
        int safeSize = Math.max(1, Math.min(size, 80));
        int offset = (safePage - 1) * safeSize;
        var records = commentMapper.pageByPostId(postId, offset, safeSize).stream().map(this::toView).toList();
        return new PageResponse<>(records, commentMapper.countByPostId(postId), safePage, safeSize);
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
        postService.requirePost(postId);
        CommentEntity comment = new CommentEntity();
        comment.setAuthorId(userId);
        comment.setPostId(postId);
        comment.setParentCommentId(request.parentCommentId());
        comment.setContent(request.content().trim());
        comment.setStatus("VISIBLE");
        commentMapper.insert(comment);
        postMapper.changeComment(postId, 1);
        postService.trackBehavior(userId, postId, "comment", "detail", null, null);
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
    public void behavior(Long userId, ApiDtos.BehaviorRequest request) {
        if (request.postId() == null) throw new BusinessException("POST_REQUIRED", "缺少图片内容");
        postService.requirePost(request.postId());
        postService.trackBehavior(userId, request.postId(), request.behaviorType(), request.scene(), request.position(), request.duration());
    }

    /**
     * Converts a comment entity into a view.
     *
     * @param comment comment entity
     * @return comment view
     */
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
