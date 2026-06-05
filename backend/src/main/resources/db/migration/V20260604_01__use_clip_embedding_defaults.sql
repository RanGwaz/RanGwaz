ALTER TABLE image_embeddings
  MODIFY vector_dimension INT NOT NULL DEFAULT 512,
  MODIFY milvus_collection VARCHAR(80) NOT NULL DEFAULT 'vibelo_image_vectors_clip_b32';
