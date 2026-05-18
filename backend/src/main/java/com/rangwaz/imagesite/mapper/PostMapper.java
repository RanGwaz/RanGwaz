package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.PostEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * Mapper for post persistence and feed reads.
 */
@Mapper
public interface PostMapper {
    /**
     * Inserts a post.
     *
     * @param post post entity
     */
    @Insert("""
            INSERT INTO posts(author_id,title,content,cover_url,thumb_url,post_type,status,like_count,favorite_count,comment_count,share_count,view_count,hot_score,published_at)
            VALUES(#{authorId},#{title},#{content},#{coverUrl},#{thumbUrl},#{postType},#{status},#{likeCount},#{favoriteCount},#{commentCount},#{shareCount},#{viewCount},#{hotScore},COALESCE(#{publishedAt},NOW()))
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    void insert(PostEntity post);

    /**
     * Finds a post by id.
     *
     * @param id post id
     * @return post entity
     */
    @Select("SELECT * FROM posts WHERE id=#{id} AND status='PUBLISHED'")
    PostEntity findById(@Param("id") Long id);

    /**
     * Counts published posts.
     *
     * @return post count
     */
    @Select("SELECT COUNT(*) FROM posts WHERE status='PUBLISHED'")
    long countPublished();

    /**
     * Selects feed posts.
     *
     * @param offset row offset
     * @param size page size
     * @return feed posts
     */
    @Select("""
            SELECT * FROM posts
            WHERE status='PUBLISHED'
            ORDER BY hot_score DESC,published_at DESC,id DESC
            LIMIT #{size} OFFSET #{offset}
            """)
    List<PostEntity> selectFeed(@Param("offset") int offset, @Param("size") int size);

    /**
     * Selects posts with nearby ids for a simple similar-content baseline.
     *
     * @param postId current post id
     * @param offset row offset
     * @param size page size
     * @return similar posts
     */
    @Select("""
            SELECT * FROM posts
            WHERE status='PUBLISHED' AND id<>#{postId}
            ORDER BY ABS(id-#{postId}),hot_score DESC
            LIMIT #{size} OFFSET #{offset}
            """)
    List<PostEntity> selectSimilar(@Param("postId") Long postId, @Param("offset") int offset, @Param("size") int size);

    /**
     * Counts similar posts for paging.
     *
     * @param postId current post id
     * @return count
     */
    @Select("SELECT COUNT(*) FROM posts WHERE status='PUBLISHED' AND id<>#{postId}")
    long countSimilar(@Param("postId") Long postId);

    /**
     * Searches posts by keyword.
     *
     * @param keyword search keyword
     * @param limit maximum rows
     * @return matching posts
     */
    @Select("""
            SELECT * FROM posts
            WHERE status='PUBLISHED' AND (title LIKE CONCAT('%',#{keyword},'%') OR content LIKE CONCAT('%',#{keyword},'%'))
            ORDER BY hot_score DESC,published_at DESC
            LIMIT #{limit}
            """)
    List<PostEntity> search(@Param("keyword") String keyword, @Param("limit") int limit);

    /**
     * Lists posts authored by a user.
     *
     * @param authorId author id
     * @param limit maximum rows
     * @return posts
     */
    @Select("""
            SELECT * FROM posts
            WHERE status='PUBLISHED' AND author_id=#{authorId}
            ORDER BY published_at DESC
            LIMIT #{limit}
            """)
    List<PostEntity> findByAuthor(@Param("authorId") Long authorId, @Param("limit") int limit);

    /**
     * Increments a post view count.
     *
     * @param postId post id
     */
    @Update("UPDATE posts SET view_count=view_count+1,hot_score=hot_score+0.08 WHERE id=#{postId}")
    void incrementView(@Param("postId") Long postId);

    /**
     * Increments a post share count.
     *
     * @param postId post id
     */
    @Update("UPDATE posts SET share_count=share_count+1,hot_score=hot_score+1.2 WHERE id=#{postId}")
    void incrementShare(@Param("postId") Long postId);

    /**
     * Changes like count.
     *
     * @param postId post id
     * @param delta count delta
     */
    @Update("UPDATE posts SET like_count=GREATEST(0,like_count+#{delta}),hot_score=GREATEST(0,hot_score+#{delta}*1.6) WHERE id=#{postId}")
    void changeLike(@Param("postId") Long postId, @Param("delta") int delta);

    /**
     * Changes favorite count.
     *
     * @param postId post id
     * @param delta count delta
     */
    @Update("UPDATE posts SET favorite_count=GREATEST(0,favorite_count+#{delta}),hot_score=GREATEST(0,hot_score+#{delta}*2.2) WHERE id=#{postId}")
    void changeFavorite(@Param("postId") Long postId, @Param("delta") int delta);

    /**
     * Changes comment count.
     *
     * @param postId post id
     * @param delta count delta
     */
    @Update("UPDATE posts SET comment_count=GREATEST(0,comment_count+#{delta}),hot_score=GREATEST(0,hot_score+#{delta}*1.3) WHERE id=#{postId}")
    void changeComment(@Param("postId") Long postId, @Param("delta") int delta);
}
