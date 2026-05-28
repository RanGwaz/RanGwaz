package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.CategoryEntity;
import com.rangwaz.imagesite.entity.ImageEntity;
import com.rangwaz.imagesite.entity.TagEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.math.BigDecimal;
import java.util.List;

/**
 * Mapper for canonical image rows and image-tag bindings.
 */
@Mapper
public interface ImageMapper {
    /**
     * Inserts a canonical image row.
     *
     * @param image image entity
     */
    @Insert("""
            INSERT INTO images(author_id,title,content,post_type,description,object_key,file_url,file_type,thumbnail_url,width,height,ratio,file_size,hash,main_category_id,status,like_count,favorite_count,comment_count,share_count,view_count,hot_score,published_at)
            VALUES(#{authorId},#{title},#{content},#{postType},#{description},#{objectKey},#{fileUrl},#{fileType},#{thumbnailUrl},#{width},#{height},#{ratio},#{fileSize},#{hash},#{mainCategoryId},#{status},#{likeCount},#{favoriteCount},#{commentCount},#{shareCount},#{viewCount},#{hotScore},COALESCE(#{publishedAt},NOW()))
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    void insert(ImageEntity image);

    /**
     * Finds an image by id.
     *
     * @param id image id
     * @return image entity
     */
    @Select("SELECT * FROM images WHERE id=#{id}")
    ImageEntity findById(@Param("id") Long id);

    /**
     * Binds a tag to an image.
     *
     * @param imageId image id
     * @param tagId tag id
     * @param confidence confidence score
     * @param source assignment source
     */
    @Insert("""
            INSERT INTO image_tags(image_id,tag_id,confidence,source)
            VALUES(#{imageId},#{tagId},#{confidence},#{source})
            ON DUPLICATE KEY UPDATE
              confidence=GREATEST(confidence,VALUES(confidence)),
              source=VALUES(source)
            """)
    void bindTag(@Param("imageId") Long imageId,
                 @Param("tagId") Long tagId,
                 @Param("confidence") BigDecimal confidence,
                 @Param("source") String source);

    /**
     * Lists typed tags attached to an image.
     *
     * @param imageId image id
     * @return tags
     */
    @Select("""
            SELECT t.* FROM tags t
            JOIN image_tags it ON it.tag_id=t.id
            WHERE it.image_id=#{imageId}
            ORDER BY t.type,t.name
            """)
    List<TagEntity> findTagsByImageId(@Param("imageId") Long imageId);

    /**
     * Lists tags with assignment fields attached to an image.
     *
     * @param imageId image id
     * @return tag assignments
     */
    @Select("""
            SELECT t.id,t.name,t.type,t.slug,it.confidence,it.source
            FROM tags t
            JOIN image_tags it ON it.tag_id=t.id
            WHERE it.image_id=#{imageId}
            ORDER BY it.confidence DESC,t.type,t.name
            """)
    List<ImageTagRow> findTagRowsByImageId(@Param("imageId") Long imageId);

    /**
     * Finds the main category for an image.
     *
     * @param imageId image id
     * @return category
     */
    @Select("""
            SELECT c.* FROM categories c
            JOIN images i ON i.main_category_id=c.id
            WHERE i.id=#{imageId}
            """)
    CategoryEntity findCategoryByImageId(@Param("imageId") Long imageId);

    /**
     * Projection for image tag views.
     */
    class ImageTagRow {
        private Long id;
        private String name;
        private String type;
        private String slug;
        private BigDecimal confidence;
        private String source;

        public Long getId() {
            return id;
        }

        public void setId(Long id) {
            this.id = id;
        }

        public String getName() {
            return name;
        }

        public void setName(String name) {
            this.name = name;
        }

        public String getType() {
            return type;
        }

        public void setType(String type) {
            this.type = type;
        }

        public String getSlug() {
            return slug;
        }

        public void setSlug(String slug) {
            this.slug = slug;
        }

        public BigDecimal getConfidence() {
            return confidence;
        }

        public void setConfidence(BigDecimal confidence) {
            this.confidence = confidence;
        }

        public String getSource() {
            return source;
        }

        public void setSource(String source) {
            this.source = source;
        }
    }
}
