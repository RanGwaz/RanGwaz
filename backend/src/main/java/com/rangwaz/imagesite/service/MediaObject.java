package com.rangwaz.imagesite.service;

/**
 * Object storage payload returned for public media reads.
 */
public record MediaObject(byte[] content, String contentType) {
}
