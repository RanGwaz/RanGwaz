package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.CategoryEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * Mapper for hierarchical image categories.
 */
@Mapper
public interface CategoryMapper {
    /**
     * Inserts a category.
     *
     * @param category category entity
     */
    @Insert("""
            INSERT INTO categories(name,parent_id,slug,sort_no)
            VALUES(#{name},#{parentId},#{slug},#{sortNo})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    void insert(CategoryEntity category);

    /**
     * Finds a category under a parent by name.
     *
     * @param name category name
     * @param parentId parent id
     * @return category entity
     */
    @Select("""
            SELECT * FROM categories
            WHERE name=#{name}
              AND ((#{parentId} IS NULL AND parent_id IS NULL) OR parent_id=#{parentId})
            LIMIT 1
            """)
    CategoryEntity findByNameAndParent(@Param("name") String name, @Param("parentId") Long parentId);

    /**
     * Finds a category by id.
     *
     * @param id category id
     * @return category entity
     */
    @Select("SELECT * FROM categories WHERE id=#{id}")
    CategoryEntity findById(@Param("id") Long id);

    /**
     * Lists all categories in tree order.
     *
     * @return categories
     */
    @Select("SELECT * FROM categories ORDER BY COALESCE(parent_id,0),sort_no,id")
    List<CategoryEntity> findAll();
}
