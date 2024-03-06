from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core import Document
from llama_index.core.schema import TextNode
import psycopg2
from sqlalchemy import make_url
import os
import pandas as pd

def setup_embeddings(embedding_model_id):
    "create sentence embeddings"
    embed_model = HuggingFaceEmbedding(model_name = embedding_model_id)
    
    return embed_model

def setup_db(
    db_name = "vector_db",
    host = "localhost",
    password = "password",
    port = "5432",
    user = "user1",
    embed_dim = 384,
    table_name = "texts"
):
    "create the Postgres table for storing vectors"
    
    # create the connection
    conn = psycopg2.connect(
        dbname = "postgres",
        host = host,
        password = password,
        port = port,
        user = user,
    )
    conn.autocommit = True

    with conn.cursor() as c:
        c.execute(f"DROP DATABASE IF EXISTS {db_name}")
        c.execute(f"CREATE DATABASE {db_name}")
        
    vector_store = PGVectorStore.from_params(
        database = db_name,
        host = host,
        password = password,
        port = port,
        user = user,
        table_name = table_name,
        embed_dim = embed_dim
    )
    
    return vector_store

def populate_db(
    vector_store,
    embed_model,
    text_path = None,
    metadata = None,
    chunk_size = 1024,
    separator = " "
):
    "populate the db with nodes from documents"
    
    # ingestion pipeline
    text_parser = SentenceSplitter(
        chunk_size = chunk_size,
        separator = separator
    )

    # creating document collection
    if type(text_path) != list:
        text_paths = [os.path.abspath(f"{text_path}{x}") for x in os.listdir(text_path)]
    else:
        text_paths = [os.path.abspath(x) for x in text_path]
    
    documents = []
    
    for text_i in text_paths:
        # read the file
        file = open(text_i, "r", encoding = "latin1")
        stringx = file.read()
        file.close()
        
        # generate the document
        metadata_i = {}
        metadata_i["filename"] = text_i
        
        if metadata is not None:
            for col in metadata.columns[metadata.columns != "file_path"]:
                value = metadata.loc[lambda x: x.file_path == text_i, col].values[0]
                value = str(value) if pd.isna(value) else value
                metadata_i[col] = value
                
        document = Document(
            text = stringx,
            metadata = metadata_i
        )
        documents.append(document)
    
    # chunking the documents
    text_chunks = []
    doc_idxs = []
    for doc_idx, doc in enumerate(documents):
        cur_text_chunks = text_parser.split_text(doc.text)
        text_chunks.extend(cur_text_chunks)
        doc_idxs.extend([doc_idx] * len(cur_text_chunks))
        
    # nodes
    nodes = []
    for idx, text_chunk in enumerate(text_chunks):
        node = TextNode(
            text=text_chunk,
        )
        src_doc = documents[doc_idxs[idx]]
        node.metadata = src_doc.metadata
        nodes.append(node)
        
    # embeddings from nodes
    for node in nodes:
        node_embedding = embed_model.get_text_embedding(
            node.get_content(metadata_mode = "all")
        )
        node.embedding = node_embedding
        
    # load nodes into the vectorstore db
    vector_store.add(nodes)