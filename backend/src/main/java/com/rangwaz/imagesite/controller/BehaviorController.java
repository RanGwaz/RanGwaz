package com.rangwaz.imagesite.controller;

import com.rangwaz.imagesite.common.api.ApiResponse;
import com.rangwaz.imagesite.common.auth.AuthContext;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.InteractionService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Behavior collection endpoint for future recommendation models.
 */
@RestController
@RequestMapping("/behaviors")
public class BehaviorController {
    private final InteractionService interactionService;
    private final AuthContext authContext;

    /**
     * Creates the behavior controller.
     *
     * @param interactionService interaction service
     * @param authContext auth context
     */
    public BehaviorController(InteractionService interactionService, AuthContext authContext) {
        this.interactionService = interactionService;
        this.authContext = authContext;
    }

    /**
     * Records a behavior event.
     *
     * @param authorization authorization header
     * @param request behavior request
     * @return empty response
     */
    @PostMapping
    public ApiResponse<Void> record(@RequestHeader(value = "Authorization", required = false) String authorization,
                                    @RequestBody ApiDtos.BehaviorRequest request) {
        interactionService.behavior(authContext.currentUserId(authorization).orElse(null), request);
        return ApiResponse.ok(null);
    }
}
