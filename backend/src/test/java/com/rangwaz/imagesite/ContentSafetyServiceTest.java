package com.rangwaz.imagesite;

import com.rangwaz.imagesite.config.ContentSafetyProperties;
import com.rangwaz.imagesite.service.ContentSafetyService;
import com.rangwaz.imagesite.service.ImageModerationClient;
import org.junit.jupiter.api.Test;

import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ContentSafetyServiceTest {
    private final ContentSafetyService contentSafetyService = new ContentSafetyService(new ContentSafetyProperties());

    @Test
    void allowsNormalSearchText() {
        assertTrue(contentSafetyService.allowsText("自然摄影 手机壁纸"));
        assertTrue(contentSafetyService.allowsText("unisex fashion outfit"));
    }

    @Test
    void blocksExplicitSearchText() {
        assertFalse(contentSafetyService.allowsText("裸 聊"));
        assertFalse(contentSafetyService.allowsText("p-o-r-n wallpaper"));
    }

    @Test
    void allowsPlaceholderProfileNickname() {
        assertDoesNotThrow(() -> contentSafetyService.requireSafeProfileText("XXX", "bbbb"));
        assertTrue(contentSafetyService.checkProfileText("XXX", "bbbb").allowed());
    }

    @Test
    void blocksExplicitProfileText() {
        assertFalse(contentSafetyService.checkProfileText("mira", "porn site").allowed());
        assertFalse(contentSafetyService.checkProfileText("测试", "色情内容").allowed());
    }

    @Test
    void allowsOrdinaryImageColors() {
        BufferedImage image = solidImage(new Color(46, 91, 178));

        assertTrue(contentSafetyService.checkImage(image).allowed());
    }

    @Test
    void blocksLargeSkinLikeExposure() {
        BufferedImage image = solidImage(new Color(220, 150, 120));

        assertFalse(contentSafetyService.checkImage(image).allowed());
        assertThrows(RuntimeException.class, () -> contentSafetyService.requireSafeImage(image, new byte[]{1, 2, 3}, "image/jpeg"));
    }

    @Test
    void allowsUploadWhenCloudModerationAllowsEvenIfLocalHeuristicWouldBlock() {
        ContentSafetyProperties properties = new ContentSafetyProperties();
        properties.getCloud().setEnabled(true);
        ContentSafetyService service = new ContentSafetyService(properties, allowingModerationClient());
        BufferedImage image = solidImage(new Color(220, 150, 120));

        assertFalse(service.checkImage(image).allowed());
        assertDoesNotThrow(() -> service.requireSafeImage(image, new byte[]{1, 2, 3}, "image/jpeg"));
    }

    @Test
    void allowsUploadWhenCloudModerationFailsOpen() {
        ContentSafetyProperties properties = new ContentSafetyProperties();
        properties.getCloud().setEnabled(true);
        properties.getCloud().setFailClosed(false);
        ContentSafetyService service = new ContentSafetyService(properties, failingModerationClient());
        BufferedImage image = solidImage(new Color(46, 91, 178));

        assertDoesNotThrow(() -> service.requireSafeCloudImage("https://example.com/image.jpg", new byte[]{1, 2, 3}, "image/jpeg"));
    }

    @Test
    void blocksUploadWhenCloudModerationFailsClosed() {
        ContentSafetyProperties properties = new ContentSafetyProperties();
        properties.getCloud().setEnabled(true);
        properties.getCloud().setFailClosed(true);
        ContentSafetyService service = new ContentSafetyService(properties, failingModerationClient());
        BufferedImage image = solidImage(new Color(46, 91, 178));

        assertThrows(RuntimeException.class, () -> service.requireSafeCloudImage("https://example.com/image.jpg", new byte[]{1, 2, 3}, "image/jpeg"));
    }

    private BufferedImage solidImage(Color color) {
        BufferedImage image = new BufferedImage(64, 64, BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics = image.createGraphics();
        try {
            graphics.setColor(color);
            graphics.fillRect(0, 0, image.getWidth(), image.getHeight());
        } finally {
            graphics.dispose();
        }
        return image;
    }

    private ImageModerationClient failingModerationClient() {
        return (imageUrl, bytes, contentType) -> {
            throw new RuntimeException("provider down");
        };
    }

    private ImageModerationClient allowingModerationClient() {
        return (imageUrl, bytes, contentType) -> ImageModerationClient.ModerationDecision.allow("test-request");
    }
}
