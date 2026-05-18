package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.entity.UserEntity;
import com.rangwaz.imagesite.mapper.FollowMapper;
import com.rangwaz.imagesite.mapper.PostMapper;
import com.rangwaz.imagesite.mapper.UserMapper;
import com.rangwaz.imagesite.service.UserService;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;

/**
 * Default user service implementation.
 */
@Service
public class UserServiceImpl implements UserService {
    private final UserMapper userMapper;
    private final PostMapper postMapper;
    private final FollowMapper followMapper;

    /**
     * Creates the user service.
     *
     * @param userMapper user mapper
     * @param postMapper post mapper
     * @param followMapper follow mapper
     */
    public UserServiceImpl(UserMapper userMapper, PostMapper postMapper, FollowMapper followMapper) {
        this.userMapper = userMapper;
        this.postMapper = postMapper;
        this.followMapper = followMapper;
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
     * @return updated summary
     */
    @Override
    public ApiDtos.UserSummary updateProfile(Long userId, ApiDtos.UpdateProfileRequest request) {
        UserEntity user = requireUser(userId);
        if (StringUtils.hasText(request.nickname())) user.setNickname(request.nickname().trim());
        if (request.avatarUrl() != null) user.setAvatarUrl(request.avatarUrl().trim());
        if (request.backgroundUrl() != null) user.setBackgroundUrl(request.backgroundUrl().trim());
        if (request.bio() != null) user.setBio(request.bio().trim());
        userMapper.updateProfile(user);
        return toSummary(userMapper.findById(userId));
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
                postMapper.findByAuthor(userId, 10_000).size(),
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

    /**
     * Loads a user or throws a business exception.
     *
     * @param userId user id
     * @return user entity
     */
    private UserEntity requireUser(Long userId) {
        UserEntity user = userMapper.findById(userId);
        if (user == null) throw new BusinessException("USER_NOT_FOUND", "用户不存在");
        return user;
    }
}
