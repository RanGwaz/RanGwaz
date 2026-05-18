package com.rangwaz.imagesite.common.api;

import java.time.OffsetDateTime;

/**
 * Standard API envelope returned to the React frontend.
 *
 * @param success whether the request succeeded
 * @param code stable response code
 * @param data response payload
 * @param message human-readable message
 * @param timestamp response creation time
 * @param <T> payload type
 */
public record ApiResponse<T>(boolean success, String code, T data, String message, OffsetDateTime timestamp) {
    /**
     * Creates a successful response.
     *
     * @param data response payload
     * @param <T> payload type
     * @return API response
     */
    public static <T> ApiResponse<T> ok(T data) {
        return new ApiResponse<>(true, "OK", data, "success", OffsetDateTime.now());
    }

    /**
     * Creates a failed response.
     *
     * @param code stable error code
     * @param message human-readable message
     * @return API response
     */
    public static ApiResponse<Void> fail(String code, String message) {
        return new ApiResponse<>(false, code, null, message, OffsetDateTime.now());
    }
}
