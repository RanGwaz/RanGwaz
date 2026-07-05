package com.rangwaz.imagesite.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Content safety controls for text queries and uploaded images.
 */
@Data
@Component
@ConfigurationProperties(prefix = "app.content-safety")
public class ContentSafetyProperties {
    private boolean enabled = true;
    private Text text = new Text();
    private Image image = new Image();
    private Cloud cloud = new Cloud();

    @Data
    public static class Text {
        private boolean enabled = true;
    }

    @Data
    public static class Image {
        private boolean enabled = true;
        private int sampleMaxWidth = 160;
        private double highSkinRatio = 0.68D;
        private double highLargestComponentRatio = 0.40D;
        private double mediumSkinRatio = 0.54D;
        private double mediumLargestComponentRatio = 0.34D;
        private double centerSkinRatio = 0.52D;
        private double lowerSkinRatio = 0.50D;
    }

    @Data
    public static class Cloud {
        private boolean enabled = false;
        private String provider = "aliyun";
        private boolean failClosed = true;
        private Aliyun aliyun = new Aliyun();
        private Model model = new Model();
    }

    @Data
    public static class Aliyun {
        private String endpoint = "https://green-cip.cn-shanghai.aliyuncs.com/";
        private String regionId = "cn-shanghai";
        private String accessKeyId = "";
        private String accessKeySecret = "";
        private String service = "baselineCheck";
        private long requestTimeoutMs = 8000L;
        private int maxBase64Bytes = 4 * 1024 * 1024;
    }

    @Data
    public static class Model {
        private String url = "http://127.0.0.1:8093/moderate/image";
        private long requestTimeoutMs = 8000L;
        private int maxBase64Bytes = 8 * 1024 * 1024;
    }
}
