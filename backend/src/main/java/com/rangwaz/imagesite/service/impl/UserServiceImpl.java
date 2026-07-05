package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.FollowMapper;
import com.rangwaz.imagesite.mapper.ImageContentMapper;
import com.rangwaz.imagesite.mapper.ProfileReviewMapper;
import com.rangwaz.imagesite.mapper.UserNotificationMapper;
import com.rangwaz.imagesite.mapper.UserMapper;
import com.rangwaz.imagesite.entity.ProfileReviewEntity;
import com.rangwaz.imagesite.entity.UserNotificationEntity;
import com.rangwaz.imagesite.service.ContentSafetyService;
import com.rangwaz.imagesite.service.UserService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Locale;

/**
 * Default user service implementation.
 */
@Service
public class UserServiceImpl implements UserService {
    private final UserMapper userMapper;
    private final ImageContentMapper imageContentMapper;
    private final FollowMapper followMapper;
    private final ProfileReviewMapper profileReviewMapper;
    private final UserNotificationMapper userNotificationMapper;
    private final ContentSafetyService contentSafetyService;

    /**
     * Creates the user service.
     *
     * @param userMapper user mapper
     * @param imageContentMapper image content mapper
     * @param followMapper follow mapper
     */
    public UserServiceImpl(UserMapper userMapper,
                           ImageContentMapper imageContentMapper,
                           FollowMapper followMapper,
                           ProfileReviewMapper profileReviewMapper,
                           UserNotificationMapper userNotificationMapper,
                           ContentSafetyService contentSafetyService) {
        this.userMapper = userMapper;
        this.imageContentMapper = imageContentMapper;
        this.followMapper = followMapper;
        this.profileReviewMapper = profileReviewMapper;
        this.userNotificationMapper = userNotificationMapper;
        this.contentSafetyService = contentSafetyService;
    }

    /**
     * Finds a user summary.
     *
     * @param userId user id
     * @return user summary
     */
    @Override
    public ApiDtos.UserSummary findSummary(Long userId) {
        return toSummary(requireUser(userId));
    }

    /**
     * Updates the current user's profile.
     *
     * @param userId current user id
     * @param request update request
     * @return created review request
     */
    @Override
    @Transactional
    public ApiDtos.ProfileReviewView updateProfile(Long userId, ApiDtos.UpdateProfileRequest request) {
        UserEntity user = requireUser(userId);
        String nickname = StringUtils.hasText(request.nickname()) ? request.nickname().trim() : user.getNickname();
        String avatarUrl = request.avatarUrl() == null ? user.getAvatarUrl() : request.avatarUrl().trim();
        String backgroundUrl = request.backgroundUrl() == null ? user.getBackgroundUrl() : request.backgroundUrl().trim();
        String bio = request.bio() == null ? user.getBio() : request.bio().trim();
        contentSafetyService.requireSafeText(String.join(" ", List.of(nickname, bio == null ? "" : bio)));

        user.setNickname(nickname);
        user.setAvatarUrl(avatarUrl);
        user.setBackgroundUrl(backgroundUrl);
        user.setBio(bio);
        userMapper.updateProfile(user);

        profileReviewMapper.supersedePending(userId);
        ProfileReviewEntity review = new ProfileReviewEntity();
        review.setUserId(userId);
        review.setNickname(nickname);
        review.setAvatarUrl(avatarUrl);
        review.setBackgroundUrl(backgroundUrl);
        review.setBio(bio);
        review.setStatus("PUBLISHED");
        profileReviewMapper.insert(review);
        profileReviewMapper.updateDecision(review.getId(), "PUBLISHED", "自动安全审核通过");
        notifyUser(userId, "PROFILE_UPDATED", "资料已更新", "头像、背景和文字资料已完成自动安全审核并生效。", "PROFILE_REVIEW", review.getId());
        return toProfileReviewView(profileReviewMapper.findById(review.getId()));
    }

    @Override
    public ApiDtos.ProfileReviewView latestProfileReview(Long userId) {
        requireUser(userId);
        return toProfileReviewView(profileReviewMapper.findLatestByUser(userId));
    }

    @Override
    public List<ApiDtos.ProfileReviewView> profileReviewQueue(String status, int limit) {
        return profileReviewMapper.findByStatus(normalizeQueueStatus(status), Math.max(1, Math.min(limit, 200))).stream()
                .map(this::toProfileReviewView)
                .toList();
    }

    @Override
    @Transactional
    public ApiDtos.ProfileReviewView decideProfileReview(Long reviewId, ApiDtos.ReviewDecisionRequest request) {
        ProfileReviewEntity review = profileReviewMapper.findById(reviewId);
        if (review == null) throw new BusinessException("PROFILE_REVIEW_NOT_FOUND", "资料审核申请不存在");
        String status = normalizeDecisionStatus(request.status());
        String reason = StringUtils.hasText(request.reason()) ? request.reason().trim() : null;
        profileReviewMapper.updateDecision(reviewId, status, reason);
        if ("PUBLISHED".equals(status)) {
            UserEntity user = requireUser(review.getUserId());
            user.setNickname(review.getNickname());
            user.setAvatarUrl(review.getAvatarUrl());
            user.setBackgroundUrl(review.getBackgroundUrl());
            user.setBio(review.getBio());
            userMapper.updateProfile(user);
            notifyUser(review.getUserId(), "PROFILE_REVIEW_APPROVED", "资料审核通过", "你的资料更新已生效。", "PROFILE_REVIEW", reviewId);
        } else {
            notifyUser(review.getUserId(), "PROFILE_REVIEW_REJECTED", "资料审核未通过", StringUtils.hasText(reason) ? reason : "资料内容不符合审核要求。", "PROFILE_REVIEW", reviewId);
        }
        return toProfileReviewView(profileReviewMapper.findById(reviewId));
    }

    /**
     * Gets user statistics.
     *
     * @param userId user id
     * @return user stats
     */
    @Override
    public ApiDtos.UserStats stats(Long userId) {
        return new ApiDtos.UserStats(
                imageContentMapper.findByAuthor(userId, 10_000).size(),
                followMapper.countFollowing(userId),
                followMapper.countFollowers(userId)
        );
    }

    /**
     * Searches users.
     *
     * @param keyword keyword
     * @param limit maximum rows
     * @return matching users
     */
    @Override
    public List<ApiDtos.UserSummary> search(String keyword, int limit) {
        return userMapper.search(keyword, Math.max(1, Math.min(limit, 50))).stream()
                .map(this::toSummary)
                .toList();
    }

    @Override
    public List<ApiDtos.NotificationView> notifications(Long userId, int limit) {
        requireUser(userId);
        return userNotificationMapper.findByUser(userId, Math.max(1, Math.min(limit, 100))).stream()
                .map(this::toNotificationView)
                .toList();
    }

    /**
     * Converts a user entity into a frontend summary.
     *
     * @param user user entity
     * @return user summary
     */
    public ApiDtos.UserSummary toSummary(UserEntity user) {
        if (user == null) return null;
        return new ApiDtos.UserSummary(
                user.getId(),
                user.getUsername(),
                user.getNickname(),
                user.getAvatarUrl(),
                user.getBackgroundUrl(),
                user.getBio()
        );
    }

    private UserEntity requireUser(Long userId) {
        UserEntity user = userMapper.findById(userId);
        if (user == null) throw new BusinessException("USER_NOT_FOUND", "用户不存在");
        return user;
    }

    private ApiDtos.ProfileReviewView toProfileReviewView(ProfileReviewEntity review) {
        if (review == null) return null;
        return new ApiDtos.ProfileReviewView(
                review.getId(),
                review.getUserId(),
                review.getNickname(),
                review.getAvatarUrl(),
                review.getBackgroundUrl(),
                review.getBio(),
                review.getStatus(),
                review.getReviewReason(),
                review.getReviewedAt(),
                review.getCreatedAt()
        );
    }

    private ApiDtos.NotificationView toNotificationView(UserNotificationEntity notification) {
        return new ApiDtos.NotificationView(
                notification.getId(),
                notification.getType(),
                notification.getTitle(),
                notification.getContent(),
                notification.getTargetType(),
                notification.getTargetId(),
                notification.getRead(),
                notification.getCreatedAt()
        );
    }

    public void notifyUser(Long userId, String type, String title, String content, String targetType, Long targetId) {
        UserNotificationEntity notification = new UserNotificationEntity();
        notification.setUserId(userId);
        notification.setType(type);
        notification.setTitle(title);
        notification.setContent(content);
        notification.setTargetType(targetType);
        notification.setTargetId(targetId);
        notification.setRead(false);
        userNotificationMapper.insert(notification);
    }

    private String normalizeDecisionStatus(String rawStatus) {
        String status = rawStatus == null ? "" : rawStatus.trim().toUpperCase(Locale.ROOT);
        if ("APPROVED".equals(status)) return "PUBLISHED";
        if ("REJECTED".equals(status)) return "REJECTED";
        if ("PUBLISHED".equals(status)) return "PUBLISHED";
        throw new BusinessException("BAD_REVIEW_STATUS", "审核状态只能是 APPROVED 或 REJECTED");
    }

    private String normalizeQueueStatus(String rawStatus) {
        String status = StringUtils.hasText(rawStatus) ? rawStatus.trim().toUpperCase(Locale.ROOT) : "PENDING_REVIEW";
        if ("PENDING_REVIEW".equals(status) || "PUBLISHED".equals(status) || "REJECTED".equals(status) || "SUPERSEDED".equals(status)) return status;
        throw new BusinessException("BAD_REVIEW_STATUS", "审核队列状态只能是 PENDING_REVIEW、PUBLISHED、REJECTED 或 SUPERSEDED");
    }
}
