package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.ImageService;
import com.rangwaz.imagesite.service.UserService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.util.StringUtils;

import java.util.List;

/**
 * Manual moderation endpoints for content and profile updates.
 */
@RestController
@RequestMapping("/moderation")
public class ModerationController {
    private final ImageService imageService;
    private final UserService userService;
    private final String reviewToken;

    public ModerationController(ImageService imageService,
                                UserService userService,
                                @Value("${app.moderation.review-token:}") String reviewToken) {
        this.imageService = imageService;
        this.userService = userService;
        this.reviewToken = reviewToken;
    }

    /**
     * Lists images waiting for manual moderation.
     *
     * @param status review status
     * @param limit maximum rows
     * @return image review queue
     */
    @GetMapping("/images")
    public ApiResponse<List<ApiDtos.ImageView>> imageQueue(@RequestHeader(value = "X-Moderation-Token", required = false) String token,
                                                           @RequestParam(defaultValue = "PENDING_REVIEW") String status,
                                                           @RequestParam(defaultValue = "50") int limit) {
        requireReviewToken(token);
        return ApiResponse.ok(imageService.reviewQueue(status, limit));
    }

    /**
     * Applies an image review decision.
     *
     * @param imageId image id
     * @param request decision request
     * @return updated image
     */
    @PostMapping("/images/{imageId}/decision")
    public ApiResponse<ApiDtos.ImageView> decideImage(@PathVariable Long imageId,
                                                      @RequestHeader(value = "X-Moderation-Token", required = false) String token,
                                                      @RequestBody ApiDtos.ReviewDecisionRequest request) {
        requireReviewToken(token);
        return ApiResponse.ok(imageService.decideImageReview(imageId, request));
    }

    /**
     * Lists profile updates waiting for manual moderation.
     *
     * @param status review status
     * @param limit maximum rows
     * @return profile review queue
     */
    @GetMapping("/profile-reviews")
    public ApiResponse<List<ApiDtos.ProfileReviewView>> profileQueue(@RequestHeader(value = "X-Moderation-Token", required = false) String token,
                                                                     @RequestParam(defaultValue = "PENDING_REVIEW") String status,
                                                                     @RequestParam(defaultValue = "50") int limit) {
        requireReviewToken(token);
        return ApiResponse.ok(userService.profileReviewQueue(status, limit));
    }

    /**
     * Applies a profile update review decision.
     *
     * @param reviewId review id
     * @param request decision request
     * @return updated profile review
     */
    @PostMapping("/profile-reviews/{reviewId}/decision")
    public ApiResponse<ApiDtos.ProfileReviewView> decideProfile(@PathVariable Long reviewId,
                                                                @RequestHeader(value = "X-Moderation-Token", required = false) String token,
                                                                @RequestBody ApiDtos.ReviewDecisionRequest request) {
        requireReviewToken(token);
        return ApiResponse.ok(userService.decideProfileReview(reviewId, request));
    }

    private void requireReviewToken(String token) {
        if (!StringUtils.hasText(reviewToken)) {
            throw new BusinessException("MODERATION_TOKEN_NOT_CONFIGURED", "审核后台令牌未配置");
        }
        if (!reviewToken.equals(token)) {
            throw new BusinessException("MODERATION_FORBIDDEN", "无审核权限");
        }
    }
}
