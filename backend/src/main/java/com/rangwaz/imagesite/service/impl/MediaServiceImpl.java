package com.rangwaz.imagesite.service.impl;

import com.rangwaz.imagesite.common.exception.BusinessException;
import com.rangwaz.imagesite.dto.ApiDtos;
import com.rangwaz.imagesite.service.MediaService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.Locale;
import java.util.UUID;

/**
 * Local filesystem media storage implementation for development.
 */
@Service
public class MediaServiceImpl implements MediaService {
    private final Path uploadRoot;
    private final String publicUploadPrefix;

    /**
     * Creates the media service.
     *
     * @param uploadRoot local upload root
     * @param publicUploadPrefix public URL prefix
     */
    public MediaServiceImpl(@Value("${app.upload-root}") String uploadRoot,
                            @Value("${app.public-upload-prefix}") String publicUploadPrefix) {
        this.uploadRoot = Path.of(uploadRoot).toAbsolutePath().normalize();
        this.publicUploadPrefix = publicUploadPrefix;
    }

    /**
     * Stores an uploaded image locally.
     *
     * @param file upload file
     * @return upload response
     */
    @Override
    public ApiDtos.UploadResponse upload(MultipartFile file) {
        if (file == null || file.isEmpty()) throw new BusinessException("EMPTY_FILE", "请选择图片");
        String contentType = file.getContentType() == null ? "" : file.getContentType().toLowerCase(Locale.ROOT);
        if (!contentType.startsWith("image/")) throw new BusinessException("BAD_FILE_TYPE", "只支持图片上传");
        String ext = extension(file.getOriginalFilename(), contentType);
        String objectKey = LocalDate.now() + "/" + UUID.randomUUID() + ext;
        Path target = uploadRoot.resolve(objectKey).normalize();
        if (!target.startsWith(uploadRoot)) throw new BusinessException("BAD_FILE_NAME", "文件名非法");
        try {
            Files.createDirectories(target.getParent());
            file.transferTo(target);
            BufferedImage image = ImageIO.read(target.toFile());
            Integer width = image == null ? null : image.getWidth();
            Integer height = image == null ? null : image.getHeight();
            String publicUrl = publicUploadPrefix + "/" + objectKey.replace("\\", "/");
            return new ApiDtos.UploadResponse(objectKey, publicUrl, "image", publicUrl, width, height);
        } catch (IOException exception) {
            throw new BusinessException("UPLOAD_FAILED", "图片保存失败");
        }
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
}
