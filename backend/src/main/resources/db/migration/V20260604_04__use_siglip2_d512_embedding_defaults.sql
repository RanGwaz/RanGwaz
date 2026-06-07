ALTER TABLE image_embeddings
  MODIFY vector_dimension INT NOT NULL DEFAULT 512,
  MODIFY milvus_collection VARCHAR(80) NOT NULL DEFAULT 'vibelo_image_vectors_siglip2_giant_p384_d512';
