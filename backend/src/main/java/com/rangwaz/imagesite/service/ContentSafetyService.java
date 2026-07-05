package com.rangwaz.imagesite.service;

import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.config.ContentSafetyProperties;
import com.rangwaz.imagesite.service.ImageModerationClient.ModerationDecision;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.awt.image.BufferedImage;
import java.text.Normalizer;
import java.util.ArrayDeque;
import java.util.List;
import java.util.Locale;
import java.util.Queue;
import java.util.regex.Pattern;

/**
 * Lightweight first-pass content safety checks for production request paths.
 */
@Service
public class ContentSafetyService {
    private static final Logger log = LoggerFactory.getLogger(ContentSafetyService.class);
    private static final List<String> BLOCKED_COMPACT_TERMS = List.of(
            "色情", "淫秽", "黄图", "黄色图片", "黄片", "裸聊", "约炮", "做爱", "口交", "肛交", "群交",
            "自慰", "成人视频", "成人图片", "成人网站", "成人内容", "性爱", "性爱图片", "性服务", "招嫖",
            "嫖娼", "卖淫", "援交", "露点", "全裸", "裸照", "裸身", "裸女", "裸男", "自拍偷拍",
            "偷拍视频", "无码", "有码", "三级片", "恋童", "儿童色情", "未成年裸", "未成年性",
            "萝莉色情", "幼女色情", "幼男色情", "强奸", "迷奸", "毒品", "冰毒", "海洛因", "可卡因",
            "摇头丸", "制毒", "贩毒", "买枪", "卖枪", "枪支交易", "博彩", "赌博", "洗钱",
            "诈骗教程", "银行卡买卖", "身份证买卖", "黑客攻击教程", "人肉搜索",
            "porn", "porno", "xxx", "hentai", "onlyfans", "blowjob", "handjob", "pussy", "penis", "vagina"
    );
    private static final Pattern ENGLISH_EXPLICIT_PATTERN = Pattern.compile(
            "(?iu)(^|[^\\p{L}\\p{N}])(sex|porn|porno|xxx|hentai|nude|naked|onlyfans|blowjob|handjob|anal|pussy|penis|vagina|boobs|cum)([^\\p{L}\\p{N}]|$)"
    );

    private final ContentSafetyProperties properties;
    private final ImageModerationClient imageModerationClient;

    @Autowired
    public ContentSafetyService(ContentSafetyProperties properties, ObjectProvider<ImageModerationClient> imageModerationClientProvider) {
        this.properties = properties;
        this.imageModerationClient = imageModerationClientProvider.getIfAvailable();
    }

    public ContentSafetyService(ContentSafetyProperties properties) {
        this.properties = properties;
        this.imageModerationClient = null;
    }

    public ContentSafetyService(ContentSafetyProperties properties, ImageModerationClient imageModerationClient) {
        this.properties = properties;
        this.imageModerationClient = imageModerationClient;
    }

    /**
     * Returns whether a search query is allowed to produce results.
     *
     * @param text user-entered query
     * @return true when the query can be processed
     */
    public boolean allowsText(String text) {
        return checkText(text).allowed();
    }

    /**
     * Throws a stable business error when user-submitted text is unsafe.
     *
     * @param text user-submitted text
     */
    public void requireSafeText(String text) {
        SafetyDecision decision = checkText(text);
        if (!decision.allowed()) {
            throw new BusinessException("UNSAFE_CONTENT", "内容不符合发布要求");
        }
    }

    /**
     * Throws a stable business error when an uploaded image is unsafe.
     *
     * @param image decoded upload image
     */
    public void requireSafeImage(BufferedImage image) {
        requireLocalSafeImage(image);
    }

    /**
     * Throws a stable business error when an uploaded image is unsafe. Cloud moderation runs first when configured.
     *
     * @param image decoded upload image
     * @param originalBytes original encoded image bytes
     * @param contentType upload content type
     */
    public void requireSafeImage(BufferedImage image, byte[] originalBytes, String contentType) {
        requireLocalSafeImage(image);
        requireCloudSafeImage(originalBytes, contentType);
    }

    /**
     * Throws a stable business error when a cloud moderation provider rejects an uploaded image URL.
     *
     * @param imageUrl public image URL fetchable by the provider
     * @param originalBytes original encoded image bytes
     * @param contentType upload content type
     */
    public void requireSafeCloudImage(String imageUrl, byte[] originalBytes, String contentType) {
        requireCloudSafeImage(imageUrl, originalBytes, contentType);
    }

    private void requireCloudSafeImage(byte[] originalBytes, String contentType) {
        requireCloudSafeImage(null, originalBytes, contentType);
    }

    private void requireCloudSafeImage(String imageUrl, byte[] originalBytes, String contentType) {
        if (!properties.isEnabled() || !properties.getCloud().isEnabled()) return;
        if (imageModerationClient == null) {
            if (properties.getCloud().isFailClosed()) {
                throw new BusinessException("IMAGE_MODERATION_NOT_CONFIGURED", "图片安全审核尚未配置");
            }
            log.warn("Image cloud moderation is enabled but no moderation client is available; continuing because failClosed=false");
            return;
        }
        ModerationDecision decision;
        try {
            decision = imageModerationClient.check(imageUrl, originalBytes, contentType);
        } catch (RuntimeException exception) {
            if (properties.getCloud().isFailClosed()) {
                throw exception;
            }
            log.warn("Image cloud moderation failed; continuing because failClosed=false error={}", exception.toString());
            return;
        }
        if (!decision.allowed()) {
            log.warn("Blocked upload by cloud image moderation reason={} requestId={}", decision.reason(), decision.requestId());
            throw new BusinessException("UNSAFE_IMAGE", "图片不符合上传要求");
        }
    }

    private void requireLocalSafeImage(BufferedImage image) {
        SafetyDecision decision = checkImage(image);
        if (!decision.allowed()) {
            log.warn("Blocked upload by local image safety rule reason={}", decision.reason());
            throw new BusinessException("UNSAFE_IMAGE", "图片不符合上传要求");
        }
    }

    /**
     * Checks free text against explicit and illegal-content patterns.
     *
     * @param text user text
     * @return decision
     */
    public SafetyDecision checkText(String text) {
        if (!properties.isEnabled() || !properties.getText().isEnabled() || !StringUtils.hasText(text)) {
            return SafetyDecision.allow();
        }
        String normalized = normalize(text);
        String compact = compact(normalized);
        if (ENGLISH_EXPLICIT_PATTERN.matcher(normalized).find()) {
            return SafetyDecision.block("explicit-text");
        }
        for (String term : BLOCKED_COMPACT_TERMS) {
            if (compact.contains(term)) {
                return SafetyDecision.block("blocked-term");
            }
        }
        return SafetyDecision.allow();
    }

    /**
     * Checks an uploaded image with a conservative skin-exposure heuristic.
     *
     * @param image decoded image
     * @return decision
     */
    public SafetyDecision checkImage(BufferedImage image) {
        if (!properties.isEnabled() || !properties.getImage().isEnabled() || image == null) {
            return SafetyDecision.allow();
        }
        ContentSafetyProperties.Image config = properties.getImage();
        int sourceWidth = image.getWidth();
        int sourceHeight = image.getHeight();
        if (sourceWidth <= 0 || sourceHeight <= 0) {
            return SafetyDecision.allow();
        }

        int sampleWidth = Math.max(1, Math.min(sourceWidth, config.getSampleMaxWidth()));
        int sampleHeight = Math.max(1, Math.round((float) sourceHeight * sampleWidth / sourceWidth));
        boolean[] skinMask = new boolean[sampleWidth * sampleHeight];
        int total = 0;
        int skin = 0;
        int centerTotal = 0;
        int centerSkin = 0;
        int lowerTotal = 0;
        int lowerSkin = 0;

        for (int y = 0; y < sampleHeight; y++) {
            int sourceY = Math.min(sourceHeight - 1, y * sourceHeight / sampleHeight);
            for (int x = 0; x < sampleWidth; x++) {
                int sourceX = Math.min(sourceWidth - 1, x * sourceWidth / sampleWidth);
                int argb = image.getRGB(sourceX, sourceY);
                int alpha = (argb >>> 24) & 0xff;
                if (alpha < 32) continue;
                total++;

                boolean center = x >= sampleWidth * 0.22D && x <= sampleWidth * 0.78D
                        && y >= sampleHeight * 0.12D && y <= sampleHeight * 0.92D;
                boolean lower = y >= sampleHeight * 0.35D;
                if (center) centerTotal++;
                if (lower) lowerTotal++;

                if (isSkinLike(argb)) {
                    skinMask[y * sampleWidth + x] = true;
                    skin++;
                    if (center) centerSkin++;
                    if (lower) lowerSkin++;
                }
            }
        }
        if (total == 0) return SafetyDecision.allow();

        double skinRatio = skin / (double) total;
        double largestComponentRatio = largestComponentRatio(skinMask, sampleWidth, sampleHeight, total);
        double centerRatio = centerTotal == 0 ? 0 : centerSkin / (double) centerTotal;
        double lowerRatio = lowerTotal == 0 ? 0 : lowerSkin / (double) lowerTotal;
        boolean highExposure = skinRatio >= config.getHighSkinRatio()
                && largestComponentRatio >= config.getHighLargestComponentRatio();
        boolean bodyLikeExposure = skinRatio >= config.getMediumSkinRatio()
                && largestComponentRatio >= config.getMediumLargestComponentRatio()
                && centerRatio >= config.getCenterSkinRatio()
                && lowerRatio >= config.getLowerSkinRatio();
        if (highExposure || bodyLikeExposure) {
            return SafetyDecision.block("skin-exposure");
        }
        return SafetyDecision.allow();
    }

    private String normalize(String text) {
        return Normalizer.normalize(text, Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
    }

    private String compact(String normalized) {
        StringBuilder builder = new StringBuilder(normalized.length());
        normalized.codePoints()
                .filter(Character::isLetterOrDigit)
                .forEach(builder::appendCodePoint);
        return builder.toString();
    }

    private boolean isSkinLike(int argb) {
        int red = (argb >> 16) & 0xff;
        int green = (argb >> 8) & 0xff;
        int blue = argb & 0xff;
        int max = Math.max(red, Math.max(green, blue));
        int min = Math.min(red, Math.min(green, blue));
        boolean rgbRule = red > 95 && green > 40 && blue > 20 && max - min > 15
                && Math.abs(red - green) > 15 && red > green && red > blue;
        double y = 0.299D * red + 0.587D * green + 0.114D * blue;
        double cb = 128D - 0.168736D * red - 0.331264D * green + 0.5D * blue;
        double cr = 128D + 0.5D * red - 0.418688D * green - 0.081312D * blue;
        boolean ycbcrRule = y > 50 && cb >= 77 && cb <= 127 && cr >= 133 && cr <= 173;
        return rgbRule && ycbcrRule;
    }

    private double largestComponentRatio(boolean[] mask, int width, int height, int totalPixels) {
        boolean[] seen = new boolean[mask.length];
        int largest = 0;
        for (int index = 0; index < mask.length; index++) {
            if (!mask[index] || seen[index]) continue;
            largest = Math.max(largest, floodFill(mask, seen, width, height, index));
        }
        return largest / (double) totalPixels;
    }

    private int floodFill(boolean[] mask, boolean[] seen, int width, int height, int startIndex) {
        Queue<Integer> queue = new ArrayDeque<>();
        queue.add(startIndex);
        seen[startIndex] = true;
        int size = 0;
        while (!queue.isEmpty()) {
            int current = queue.remove();
            size++;
            int x = current % width;
            int y = current / width;
            addNeighbor(mask, seen, queue, x - 1, y, width, height);
            addNeighbor(mask, seen, queue, x + 1, y, width, height);
            addNeighbor(mask, seen, queue, x, y - 1, width, height);
            addNeighbor(mask, seen, queue, x, y + 1, width, height);
        }
        return size;
    }

    private void addNeighbor(boolean[] mask, boolean[] seen, Queue<Integer> queue, int x, int y, int width, int height) {
        if (x < 0 || y < 0 || x >= width || y >= height) return;
        int index = y * width + x;
        if (!mask[index] || seen[index]) return;
        seen[index] = true;
        queue.add(index);
    }

    public record SafetyDecision(boolean allowed, String reason) {
        public static SafetyDecision allow() {
            return new SafetyDecision(true, null);
        }

        public static SafetyDecision block(String reason) {
            return new SafetyDecision(false, reason);
        }
    }
}
