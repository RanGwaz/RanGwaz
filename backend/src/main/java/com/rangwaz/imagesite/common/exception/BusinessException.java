package com.rangwaz.imagesite.common.exception;

/**
 * Exception for expected business failures that should become stable API errors.
 */
public class BusinessException extends RuntimeException {
    private final String code;

    /**
     * Creates a business exception.
     *
     * @param code stable error code
     * @param message human-readable message
     */
    public BusinessException(String code, String message) {
        super(message);
        this.code = code;
    }

    /**
     * Returns the stable error code.
     *
     * @return error code
     */
    public String getCode() {
        return code;
    }
}
