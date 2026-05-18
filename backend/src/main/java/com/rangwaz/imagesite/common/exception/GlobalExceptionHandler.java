package com.rangwaz.imagesite.common.exception;

import com.rangwaz.imagesite.common.api.ApiResponse;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * Converts backend exceptions into the shared API envelope.
 */
@RestControllerAdvice
public class GlobalExceptionHandler {
    /**
     * Handles expected business failures.
     *
     * @param exception business exception
     * @return API error response
     */
    @ExceptionHandler(BusinessException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ApiResponse<Void> handleBusiness(BusinessException exception) {
        return ApiResponse.fail(exception.getCode(), exception.getMessage());
    }

    /**
     * Handles validation failures.
     *
     * @param exception validation exception
     * @return API error response
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public ApiResponse<Void> handleValidation(MethodArgumentNotValidException exception) {
        String message = exception.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(error -> error.getField() + " " + error.getDefaultMessage())
                .orElse("参数校验失败");
        return ApiResponse.fail("VALIDATION_ERROR", message);
    }

    /**
     * Handles unexpected failures.
     *
     * @param exception exception
     * @return API error response
     */
    @ExceptionHandler(Exception.class)
    @ResponseStatus(HttpStatus.INTERNAL_SERVER_ERROR)
    public ApiResponse<Void> handleUnknown(Exception exception) {
        return ApiResponse.fail("INTERNAL_ERROR", exception.getMessage());
    }
}
