package com.rangwaz.imagesite.mapper;

import com.rangwaz.imagesite.entity.CategoryEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * Mapper for globally unique image categories.
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
     * Finds a category by globally unique name.
     *
     * @param name category name
     * @return category entity
     */
    @Select("SELECT * FROM categories WHERE name=#{name} LIMIT 1")
    CategoryEntity findByName(@Param("name") String name);

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
