package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.ImageEntity;
import com.rangwaz.imagesite.entity.ImageSearchDocumentEntity;
import com.rangwaz.imagesite.entity.SearchSuggestionEntity;
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
     * Finds image content by id without status filtering.
     *
     * @param id image id
     * @return image content entity
     */
    @Select("SELECT * FROM images WHERE id=#{id}")
    ImageEntity findAnyById(@Param("id") Long id);

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
     * Finds published images by ids while preserving the input order.
     *
     * @param ids ordered image ids
     * @return image content rows
     */
    @Select("""
            <script>
            SELECT * FROM images
            WHERE status='PUBLISHED'
              AND id IN
              <foreach collection="ids" item="id" open="(" separator="," close=")">
                #{id}
              </foreach>
            ORDER BY FIELD(id,
              <foreach collection="ids" item="id" separator=",">
                #{id}
              </foreach>
            )
            </script>
            """)
    List<ImageEntity> findPublishedByIds(@Param("ids") List<Long> ids);

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
     * Searches image content by text, category, and tag metadata.
     *
     * @param keywords expanded search keywords
     * @param limit maximum rows
     * @return matching image content
     */
    @Select("""
            <script>
            SELECT i.*
            FROM images i
            JOIN (
              SELECT id, MAX(rank_score) AS relevance, MAX(hot_score) AS hot_score, MAX(published_at) AS published_at
              FROM (
                <foreach collection="keywords" item="keyword" separator=" UNION ALL ">
                  SELECT id, 50 AS rank_score, hot_score, published_at
                  FROM images
                  WHERE status='PUBLISHED' AND title LIKE CONCAT('%',#{keyword},'%')
                  UNION ALL
                  SELECT id, 36 AS rank_score, hot_score, published_at
                  FROM images
                  WHERE status='PUBLISHED'
                    AND (content LIKE CONCAT('%',#{keyword},'%') OR description LIKE CONCAT('%',#{keyword},'%'))
                  UNION ALL
                  SELECT i.id, 42 AS rank_score, i.hot_score, i.published_at
                  FROM tags t
                  JOIN image_tags it ON it.tag_id=t.id
                  JOIN images i ON i.id=it.image_id
                  WHERE i.status='PUBLISHED'
                    AND (t.name LIKE CONCAT('%',#{keyword},'%') OR t.slug LIKE CONCAT('%',#{keyword},'%'))
                  UNION ALL
                  SELECT i.id, 40 AS rank_score, i.hot_score, i.published_at
                  FROM categories c
                  JOIN images i ON i.main_category_id=c.id
                  WHERE i.status='PUBLISHED'
                    AND (c.name LIKE CONCAT('%',#{keyword},'%') OR c.slug LIKE CONCAT('%',#{keyword},'%'))
                </foreach>
              ) hits
              GROUP BY id
              ORDER BY relevance DESC, hot_score DESC, published_at DESC, id DESC
              LIMIT #{limit}
            ) ranked ON ranked.id=i.id
            ORDER BY ranked.relevance DESC, ranked.hot_score DESC, ranked.published_at DESC, ranked.id DESC
            </script>
            """)
    List<ImageEntity> searchExpanded(@Param("keywords") List<String> keywords, @Param("limit") int limit);

    /**
     * Suggests search ideas from tag and category metadata.
     *
     * @param keywords optional expanded keywords
     * @param limit maximum rows
     * @return suggestion rows with representative thumbnails
     */
    @Select("""
            <script>
            WITH
            candidate_tags AS (
              SELECT id, name
              FROM tags
              WHERE 1=1
              <if test="keywords != null and keywords.size() > 0">
                AND (
                  <foreach collection="keywords" item="keyword" separator=" OR ">
                    name LIKE CONCAT('%',#{keyword},'%') OR slug LIKE CONCAT('%',#{keyword},'%')
                  </foreach>
                )
              </if>
              ORDER BY name
              LIMIT 80
            ),
            tag_suggestions AS (
              SELECT ct.name AS keyword,
                     'tag' AS kind,
                     MIN(COALESCE(i.thumbnail_url,i.file_url)) AS imageUrl,
                     COUNT(*) AS postCount
              FROM candidate_tags ct
              JOIN image_tags it ON it.tag_id=ct.id
              JOIN images i ON i.id=it.image_id AND i.status='PUBLISHED'
              GROUP BY ct.id, ct.name
            ),
            candidate_categories AS (
              SELECT id, name, sort_no
              FROM categories
              WHERE 1=1
              <if test="keywords != null and keywords.size() > 0">
                AND (
                  <foreach collection="keywords" item="keyword" separator=" OR ">
                    name LIKE CONCAT('%',#{keyword},'%') OR slug LIKE CONCAT('%',#{keyword},'%')
                  </foreach>
                )
              </if>
              ORDER BY sort_no, name
              LIMIT 32
            ),
            category_suggestions AS (
              SELECT cc.name AS keyword,
                     'category' AS kind,
                     MIN(COALESCE(i.thumbnail_url,i.file_url)) AS imageUrl,
                     COUNT(*) AS postCount
              FROM candidate_categories cc
              JOIN images i ON i.main_category_id=cc.id AND i.status='PUBLISHED'
              GROUP BY cc.id, cc.name
            ),
            candidate_topics AS (
              SELECT name, cover_url, post_count, hot_score
              FROM topics
              WHERE post_count > 0
              <if test="keywords != null and keywords.size() > 0">
                AND (
                  <foreach collection="keywords" item="keyword" separator=" OR ">
                    name LIKE CONCAT('%',#{keyword},'%') OR slug LIKE CONCAT('%',#{keyword},'%')
                  </foreach>
                )
              </if>
              ORDER BY hot_score DESC, post_count DESC, name
              LIMIT 32
            )
            SELECT keyword, kind, imageUrl, postCount
            FROM (
              SELECT keyword, kind, imageUrl, postCount FROM tag_suggestions
              UNION ALL
              SELECT keyword, kind, imageUrl, postCount FROM category_suggestions
              UNION ALL
              SELECT name AS keyword, 'topic' AS kind, cover_url AS imageUrl, post_count AS postCount
              FROM candidate_topics
            ) suggestions
            WHERE keyword IS NOT NULL AND keyword&lt;&gt;'' AND postCount > 0
            ORDER BY postCount DESC, keyword
            LIMIT #{limit}
            </script>
            """)
    List<SearchSuggestionEntity> suggestByMetadata(@Param("keywords") List<String> keywords, @Param("limit") int limit);

    /**
     * Selects published image documents for search indexing by ids.
     *
     * @param ids image ids
     * @return search documents
     */
    @Select("""
            <script>
            SELECT i.id,
                   i.author_id,
                   i.title,
                   i.content,
                   i.description,
                   i.status,
                   i.file_url,
                   i.thumbnail_url,
                   i.width,
                   i.height,
                   i.ratio,
                   u.username AS author_username,
                   u.nickname AS author_nickname,
                   c.name AS category_name,
                   GROUP_CONCAT(DISTINCT t.name ORDER BY it.confidence DESC,t.name SEPARATOR ',') AS tags_csv,
                   GROUP_CONCAT(DISTINCT tp.name ORDER BY tp.hot_score DESC,tp.name SEPARATOR ',') AS topics_csv,
                   i.hot_score,
                   i.published_at,
                   i.created_at
            FROM images i
            LEFT JOIN app_users u ON u.id=i.author_id
            LEFT JOIN categories c ON c.id=i.main_category_id
            LEFT JOIN image_tags it ON it.image_id=i.id
            LEFT JOIN tags t ON t.id=it.tag_id
            LEFT JOIN image_topics ixt ON ixt.image_id=i.id
            LEFT JOIN topics tp ON tp.id=ixt.topic_id
            WHERE i.status='PUBLISHED'
              AND i.id IN
              <foreach collection="ids" item="id" open="(" separator="," close=")">
                #{id}
              </foreach>
            GROUP BY i.id,i.author_id,i.title,i.content,i.description,i.status,i.file_url,i.thumbnail_url,
                     i.width,i.height,i.ratio,
                     u.username,u.nickname,c.name,i.hot_score,i.published_at,i.created_at
            ORDER BY FIELD(i.id,
              <foreach collection="ids" item="id" separator=",">
                #{id}
              </foreach>
            )
            </script>
            """)
    List<ImageSearchDocumentEntity> findSearchDocumentsByIds(@Param("ids") List<Long> ids);

    /**
     * Pages published image documents for full search reindexing.
     *
     * @param afterId last indexed image id
     * @param limit page size
     * @return search documents
     */
    @Select("""
            SELECT i.id,
                   i.author_id,
                   i.title,
                   i.content,
                   i.description,
                   i.status,
                   i.file_url,
                   i.thumbnail_url,
                   i.width,
                   i.height,
                   i.ratio,
                   u.username AS author_username,
                   u.nickname AS author_nickname,
                   c.name AS category_name,
                   GROUP_CONCAT(DISTINCT t.name ORDER BY it.confidence DESC,t.name SEPARATOR ',') AS tags_csv,
                   GROUP_CONCAT(DISTINCT tp.name ORDER BY tp.hot_score DESC,tp.name SEPARATOR ',') AS topics_csv,
                   i.hot_score,
                   i.published_at,
                   i.created_at
            FROM images i
            LEFT JOIN app_users u ON u.id=i.author_id
            LEFT JOIN categories c ON c.id=i.main_category_id
            LEFT JOIN image_tags it ON it.image_id=i.id
            LEFT JOIN tags t ON t.id=it.tag_id
            LEFT JOIN image_topics ixt ON ixt.image_id=i.id
            LEFT JOIN topics tp ON tp.id=ixt.topic_id
            WHERE i.status='PUBLISHED' AND i.id>#{afterId}
            GROUP BY i.id,i.author_id,i.title,i.content,i.description,i.status,i.file_url,i.thumbnail_url,
                     i.width,i.height,i.ratio,
                     u.username,u.nickname,c.name,i.hot_score,i.published_at,i.created_at
            ORDER BY i.id
            LIMIT #{limit}
            """)
    List<ImageSearchDocumentEntity> pageSearchDocuments(@Param("afterId") Long afterId, @Param("limit") int limit);

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
     * Lists all image content authored by a user for owner review status pages.
     *
     * @param authorId author id
     * @param limit maximum rows
     * @return image content rows
     */
    @Select("""
            SELECT * FROM images
            WHERE author_id=#{authorId}
            ORDER BY created_at DESC,id DESC
            LIMIT #{limit}
            """)
    List<ImageEntity> findAllByAuthor(@Param("authorId") Long authorId, @Param("limit") int limit);

    /**
     * Lists image content by review status for manual moderation.
     *
     * @param status review status
     * @param limit maximum rows
     * @return image content rows
     */
    @Select("""
            SELECT * FROM images
            WHERE status=#{status}
            ORDER BY created_at ASC,id ASC
            LIMIT #{limit}
            """)
    List<ImageEntity> findByStatus(@Param("status") String status, @Param("limit") int limit);

    /**
     * Updates moderation status.
     *
     * @param id image id
     * @param status status
     * @param reason reason
     */
    @Update("""
            UPDATE images
            SET status=#{status},review_reason=#{reason},reviewed_at=NOW(),
                published_at=CASE WHEN #{status}='PUBLISHED' THEN NOW() ELSE published_at END
            WHERE id=#{id}
            """)
    void updateReviewStatus(@Param("id") Long id, @Param("status") String status, @Param("reason") String reason);

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
