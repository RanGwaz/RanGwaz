package com.rangwaz.imagesite;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Starts the RanGwaz image-site backend.
 */
@MapperScan("com.rangwaz.imagesite.mapper")
@SpringBootApplication
public class ImageSiteApplication {
    /**
     * Launches the Spring Boot application.
     *
     * @param args command-line arguments
     */
    public static void main(String[] args) {
        SpringApplication.run(ImageSiteApplication.class, args);
    }
}
