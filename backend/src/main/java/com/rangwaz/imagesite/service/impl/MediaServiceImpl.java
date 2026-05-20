package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.config.MinioProperties;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.MediaObject;
import com.rangwaz.imagesite.service.MediaService;
import io.minio.BucketExistsArgs;
import io.minio.GetObjectArgs;
import io.minio.MakeBucketArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.util.StringUtils;

import javax.imageio.ImageIO;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.time.LocalDate;
import java.util.Locale;
import java.util.UUID;

/**
 * MinIO media storage implementation.
 */
@Service
public class MediaServiceImpl implements MediaService {
    private static final int THUMBNAIL_MAX_WIDTH = 520;

    private final MinioClient minioClient;
    private final MinioProperties properties;

    /**
     * Creates the media storage service.
     *
     * @param minioClient MinIO client
     * @param properties MinIO properties
     */
    public MediaServiceImpl(MinioClient minioClient, MinioProperties properties) {
        this.minioClient = minioClient;
        this.properties = properties;
    }

    /**
     * Stores an uploaded image in MinIO and creates a JPEG thumbnail.
     *
     * @param file upload file
     * @return upload response
     */
    @Override
    public ApiDtos.UploadResponse upload(MultipartFile file) {
        if (file == null || file.isEmpty()) throw new BusinessException("EMPTY_FILE", "请选择图片");
        String contentType = file.getContentType() == null ? "" : file.getContentType().toLowerCase(Locale.ROOT);
        if (!contentType.startsWith("image/")) throw new BusinessException("BAD_FILE_TYPE", "只支持图片上传");
        try {
            ensureBucket();
            byte[] originalBytes = file.getBytes();
            BufferedImage image = ImageIO.read(new ByteArrayInputStream(originalBytes));
            if (image == null) throw new BusinessException("BAD_IMAGE", "图片解析失败");
            String ext = extension(file.getOriginalFilename(), contentType);
            String datePath = LocalDate.now().toString().replace("-", "/");
            String uuid = UUID.randomUUID().toString();
            String originalKey = "originals/" + datePath + "/" + uuid + ext;
            String thumbKey = "thumbs/" + datePath + "/" + uuid + ".jpg";
            putObject(originalKey, originalBytes, contentType);
            putObject(thumbKey, thumbnailBytes(image), "image/jpeg");
            return new ApiDtos.UploadResponse(
                    originalKey,
                    publicUrl(originalKey),
                    "image",
                    publicUrl(thumbKey),
                    image.getWidth(),
                    image.getHeight()
            );
        } catch (BusinessException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new BusinessException("UPLOAD_FAILED", "图片保存失败");
        }
    }

    /**
     * Reads a MinIO object into memory for browser delivery.
     *
     * @param objectKey object key
     * @return media object
     */
    @Override
    public MediaObject read(String objectKey) {
        String safeKey = normalizeObjectKey(objectKey);
        try (InputStream input = minioClient.getObject(GetObjectArgs.builder()
                .bucket(properties.getBucket())
                .object(safeKey)
                .build())) {
            return new MediaObject(input.readAllBytes(), contentType(safeKey));
        } catch (Exception exception) {
            throw new BusinessException("MEDIA_NOT_FOUND", "图片不存在");
        }
    }

    /**
     * Creates the MinIO bucket if it does not exist.
     */
    private void ensureBucket() throws Exception {
        boolean exists = minioClient.bucketExists(BucketExistsArgs.builder()
                .bucket(properties.getBucket())
                .build());
        if (!exists) {
            minioClient.makeBucket(MakeBucketArgs.builder()
                    .bucket(properties.getBucket())
                    .build());
        }
    }

    /**
     * Uploads bytes to MinIO.
     *
     * @param objectKey object key
     * @param bytes payload
     * @param contentType content type
     */
    private void putObject(String objectKey, byte[] bytes, String contentType) throws Exception {
        minioClient.putObject(PutObjectArgs.builder()
                .bucket(properties.getBucket())
                .object(objectKey)
                .stream(new ByteArrayInputStream(bytes), bytes.length, -1)
                .contentType(contentType)
                .build());
    }

    /**
     * Builds a public URL routed through the backend.
     *
     * @param objectKey object key
     * @return public URL
     */
    private String publicUrl(String objectKey) {
        String prefix = StringUtils.hasText(properties.getObjectUrlPrefix())
                ? properties.getObjectUrlPrefix()
                : "/api/media/object";
        return prefix.replaceAll("/$", "") + "/" + objectKey;
    }

    /**
     * Creates a thumbnail JPEG while keeping the image aspect ratio.
     *
     * @param image source image
     * @return JPEG bytes
     */
    private byte[] thumbnailBytes(BufferedImage image) throws Exception {
        int width = image.getWidth();
        int height = image.getHeight();
        if (width > THUMBNAIL_MAX_WIDTH) {
            height = Math.max(1, Math.round((float) height * THUMBNAIL_MAX_WIDTH / width));
            width = THUMBNAIL_MAX_WIDTH;
        }
        BufferedImage thumb = new BufferedImage(width, height, BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics = thumb.createGraphics();
        try {
            graphics.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BICUBIC);
            graphics.setRenderingHint(RenderingHints.KEY_RENDERING, RenderingHints.VALUE_RENDER_QUALITY);
            graphics.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            graphics.drawImage(image, 0, 0, width, height, null);
        } finally {
            graphics.dispose();
        }
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        ImageIO.write(thumb, "jpg", output);
        return output.toByteArray();
    }

    /**
     * Resolves a safe file extension.
     *
     * @param original original filename
     * @param contentType content type
     * @return extension
     */
    private String extension(String original, String contentType) {
        if (original != null && original.lastIndexOf('.') >= 0) {
            String ext = original.substring(original.lastIndexOf('.')).toLowerCase(Locale.ROOT);
            if (ext.matches("\\.(jpg|jpeg|png|gif|webp)")) return ext;
        }
        return switch (contentType) {
            case "image/png" -> ".png";
            case "image/gif" -> ".gif";
            case "image/webp" -> ".webp";
            default -> ".jpg";
        };
    }

    /**
     * Infers the browser content type from an object key.
     *
     * @param objectKey object key
     * @return content type
     */
    private String contentType(String objectKey) {
        String lower = objectKey.toLowerCase(Locale.ROOT);
        if (lower.endsWith(".png")) return "image/png";
        if (lower.endsWith(".gif")) return "image/gif";
        if (lower.endsWith(".webp")) return "image/webp";
        return "image/jpeg";
    }

    /**
     * Normalizes a public object key.
     *
     * @param objectKey object key
     * @return safe key
     */
    private String normalizeObjectKey(String objectKey) {
        String key = objectKey == null ? "" : objectKey.replace("\\", "/");
        while (key.startsWith("/")) key = key.substring(1);
        if (!StringUtils.hasText(key) || key.contains("..")) {
            throw new BusinessException("BAD_OBJECT_KEY", "图片地址非法");
        }
        return key;
    }
}
