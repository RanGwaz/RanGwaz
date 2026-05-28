package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.ImageEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * Mapper for the canonical images table used as publishable content.
 */
@Mapper
public interface ImageContentMapper {
    /**
     * Inserts one image content row.
     *
     * @param image image content entity
     */
    @Insert("""
            INSERT INTO images(author_id,title,content,post_type,description,object_key,file_url,file_type,thumbnail_url,width,height,ratio,file_size,hash,main_category_id,status,like_count,favorite_count,comment_count,share_count,view_count,hot_score,published_at)
            VALUES(#{authorId},#{title},#{content},#{postType},#{description},#{objectKey},#{fileUrl},#{fileType},#{thumbnailUrl},#{width},#{height},#{ratio},#{fileSize},#{hash},#{mainCategoryId},#{status},#{likeCount},#{favoriteCount},#{commentCount},#{shareCount},#{viewCount},#{hotScore},COALESCE(#{publishedAt},NOW()))
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    void insert(ImageEntity image);

    /**
     * Finds published image content by id.
     *
     * @param id image id
     * @return image content entity
     */
    @Select("SELECT * FROM images WHERE id=#{id} AND status='PUBLISHED'")
    ImageEntity findById(@Param("id") Long id);

    /**
     * Counts published image content.
     *
     * @return image count
     */
    @Select("SELECT COUNT(*) FROM images WHERE status='PUBLISHED'")
    long countPublished();

    /**
     * Selects home feed image content.
     *
     * @param offset row offset
     * @param size page size
     * @return image content rows
     */
    @Select("""
            SELECT * FROM images
            WHERE status='PUBLISHED'
            ORDER BY hot_score DESC,published_at DESC,id DESC
            LIMIT #{size} OFFSET #{offset}
            """)
    List<ImageEntity> selectFeed(@Param("offset") int offset, @Param("size") int size);

    /**
     * Selects nearby image content for a simple similar baseline.
     *
     * @param postId current image id
     * @param offset row offset
     * @param size page size
     * @return image content rows
     */
    @Select("""
            SELECT * FROM images
            WHERE status='PUBLISHED' AND id<>#{postId}
            ORDER BY ABS(id-#{postId}),hot_score DESC
            LIMIT #{size} OFFSET #{offset}
            """)
    List<ImageEntity> selectSimilar(@Param("postId") Long postId, @Param("offset") int offset, @Param("size") int size);

    /**
     * Counts similar image content for paging.
     *
     * @param postId current image id
     * @return count
     */
    @Select("SELECT COUNT(*) FROM images WHERE status='PUBLISHED' AND id<>#{postId}")
    long countSimilar(@Param("postId") Long postId);

    /**
     * Searches image content by keyword.
     *
     * @param keyword search keyword
     * @param limit maximum rows
     * @return matching image content
     */
    @Select("""
            SELECT * FROM images
            WHERE status='PUBLISHED'
              AND (title LIKE CONCAT('%',#{keyword},'%')
                   OR content LIKE CONCAT('%',#{keyword},'%')
                   OR description LIKE CONCAT('%',#{keyword},'%'))
            ORDER BY hot_score DESC,published_at DESC
            LIMIT #{limit}
            """)
    List<ImageEntity> search(@Param("keyword") String keyword, @Param("limit") int limit);

    /**
     * Lists image content authored by a user.
     *
     * @param authorId author id
     * @param limit maximum rows
     * @return image content rows
     */
    @Select("""
            SELECT * FROM images
            WHERE status='PUBLISHED' AND author_id=#{authorId}
            ORDER BY published_at DESC
            LIMIT #{limit}
            """)
    List<ImageEntity> findByAuthor(@Param("authorId") Long authorId, @Param("limit") int limit);

    /**
     * Increments view count.
     *
     * @param postId image id exposed as post id
     */
    @Update("UPDATE images SET view_count=view_count+1,hot_score=hot_score+0.08 WHERE id=#{postId}")
    void incrementView(@Param("postId") Long postId);

    /**
     * Increments share count.
     *
     * @param postId image id exposed as post id
     */
    @Update("UPDATE images SET share_count=share_count+1,hot_score=hot_score+1.2 WHERE id=#{postId}")
    void incrementShare(@Param("postId") Long postId);

    /**
     * Changes like count.
     *
     * @param postId image id exposed as post id
     * @param delta count delta
     */
    @Update("UPDATE images SET like_count=GREATEST(0,like_count+#{delta}),hot_score=GREATEST(0,hot_score+#{delta}*1.6) WHERE id=#{postId}")
    void changeLike(@Param("postId") Long postId, @Param("delta") int delta);

    /**
     * Changes favorite count.
     *
     * @param postId image id exposed as post id
     * @param delta count delta
     */
    @Update("UPDATE images SET favorite_count=GREATEST(0,favorite_count+#{delta}),hot_score=GREATEST(0,hot_score+#{delta}*2.2) WHERE id=#{postId}")
    void changeFavorite(@Param("postId") Long postId, @Param("delta") int delta);

    /**
     * Changes comment count.
     *
     * @param postId image id exposed as post id
     * @param delta count delta
     */
    @Update("UPDATE images SET comment_count=GREATEST(0,comment_count+#{delta}),hot_score=GREATEST(0,hot_score+#{delta}*1.3) WHERE id=#{postId}")
    void changeComment(@Param("postId") Long postId, @Param("delta") int delta);
}
