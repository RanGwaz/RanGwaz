package com.rangwaz.imagesite.common.api;

import java.util.List;

/**
 * Page payload used by feed, comments, and search endpoints.
 *
 * @param records page records
 * @param total total matching records
 * @param page current page number
 * @param size requested page size
 * @param <T> record type
 */
public record PageResponse<T>(List<T> records, long total, int page, int size) {
}
