-- Optimized RAG Bot Database Schema (Production Ready)
-- This setup incorporates all performance best practices from the start

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;  -- For query monitoring
CREATE EXTENSION IF NOT EXISTS btree_gin;           -- For composite GIN indexes

-- =============================================================================
-- OPTIMIZED TABLE STRUCTURE
-- =============================================================================

-- 1. Document chunks table (optimized structure)
CREATE TABLE chunks (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector(384) NOT NULL,  -- all-MiniLM-L6-v2 embeddings
    file_id TEXT NOT NULL,           -- Direct field instead of JSONB for performance
    filename TEXT NOT NULL,          -- Direct field for faster filtering
    file_path TEXT,                  -- Full path for reference
    citation_url TEXT,
    chunk_index INTEGER NOT NULL DEFAULT 0,  -- Position within document
    word_count INTEGER,              -- For filtering very short chunks
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Additional metadata as JSONB for flexibility
    metadata JSONB DEFAULT '{}'::jsonb,
    
    -- Constraints
    CONSTRAINT chunks_content_not_empty CHECK (length(trim(content)) > 10),
    CONSTRAINT chunks_word_count_check CHECK (word_count > 0)
);

-- 2. File permissions table (optimized for fast lookups)
CREATE TABLE file_permissions (
    id BIGSERIAL PRIMARY KEY,
    file_id TEXT NOT NULL,
    drive_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    permission_id TEXT NOT NULL,
    permission_type TEXT NOT NULL,           -- user, group, link, etc.
    role_name TEXT NOT NULL,                 -- read, write, owner, etc.
    granted_to_user_id TEXT,
    granted_to_user_email TEXT,
    granted_to_group_id TEXT,
    granted_to_group_name TEXT,
    link_type TEXT,                          -- view, edit, anonymous
    link_scope TEXT,                         -- anonymous, organization, users
    expires_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT true,          -- For soft deletes
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Unique constraint to prevent duplicates
    CONSTRAINT unique_file_permission UNIQUE(file_id, permission_id)
);

-- 3. Pre-computed user access view (materialized for performance)
CREATE TABLE user_accessible_files (
    file_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_email TEXT,
    access_type TEXT NOT NULL,  -- direct, group, link
    role_name TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (file_id, user_id)
);

-- 4. Conversations table (optimized)
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    channel_id TEXT,
    tenant_id TEXT,                          -- For multi-tenant setups
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_activity_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_conversation UNIQUE(conversation_id, user_id)
);

-- 5. Messages table (with partitioning for scale)
CREATE TABLE messages (
    id BIGSERIAL,
    conversation_uuid UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    message_id TEXT,
    tokens_used INTEGER,                     -- For cost tracking
    model_used TEXT,                         -- Track which model was used
    response_time_ms INTEGER,                -- Track performance
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (id, created_at)            -- Composite primary key for partitioning
) PARTITION BY RANGE (created_at);

-- Create monthly partitions for messages (automatically managed)
CREATE TABLE messages_2024_01 PARTITION OF messages
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE messages_2024_02 PARTITION OF messages
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
CREATE TABLE messages_2024_03 PARTITION OF messages
    FOR VALUES FROM ('2024-03-01') TO ('2024-04-01');
CREATE TABLE messages_2024_04 PARTITION OF messages
    FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');
CREATE TABLE messages_2024_05 PARTITION OF messages
    FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
CREATE TABLE messages_2024_06 PARTITION OF messages
    FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');
CREATE TABLE messages_2024_07 PARTITION OF messages
    FOR VALUES FROM ('2024-07-01') TO ('2024-08-01');
CREATE TABLE messages_2024_08 PARTITION OF messages
    FOR VALUES FROM ('2024-08-01') TO ('2024-09-01');
CREATE TABLE messages_2024_09 PARTITION OF messages
    FOR VALUES FROM ('2024-09-01') TO ('2024-10-01');
CREATE TABLE messages_2024_10 PARTITION OF messages
    FOR VALUES FROM ('2024-10-01') TO ('2024-11-01');
CREATE TABLE messages_2024_11 PARTITION OF messages
    FOR VALUES FROM ('2024-11-01') TO ('2024-12-01');
CREATE TABLE messages_2024_12 PARTITION OF messages
    FOR VALUES FROM ('2024-12-01') TO ('2025-01-01');

-- 6. Delta sync tracking (for OneDrive sync)
CREATE TABLE delta_links (
    id BIGSERIAL PRIMARY KEY,
    drive_id TEXT NOT NULL UNIQUE,
    delta_link TEXT NOT NULL,
    last_sync_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    sync_status TEXT DEFAULT 'active',       -- active, paused, error
    error_message TEXT,
    files_processed INTEGER DEFAULT 0,
    chunks_created INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- OPTIMIZED INDEXES (PRODUCTION READY)
-- =============================================================================

-- Vector similarity indexes (tuned for performance)
CREATE INDEX chunks_embedding_cosine_idx ON chunks 
USING ivfflat (embedding vector_cosine_ops) 
WITH (lists = 100);

CREATE INDEX chunks_embedding_ip_idx ON chunks 
USING ivfflat (embedding vector_ip_ops) 
WITH (lists = 100);

-- High-performance composite indexes
CREATE INDEX chunks_file_lookup_idx ON chunks (file_id, chunk_index);
CREATE INDEX chunks_filename_idx ON chunks (filename);
CREATE INDEX chunks_content_search_idx ON chunks USING gin(to_tsvector('english', content));
CREATE INDEX chunks_created_at_idx ON chunks (created_at DESC);
CREATE INDEX chunks_word_count_idx ON chunks (word_count) WHERE word_count > 50;

-- Permission lookup indexes
CREATE INDEX file_permissions_user_lookup_idx ON file_permissions (granted_to_user_id, is_active) WHERE is_active = true;
CREATE INDEX file_permissions_email_lookup_idx ON file_permissions (granted_to_user_email, is_active) WHERE is_active = true;
CREATE INDEX file_permissions_file_lookup_idx ON file_permissions (file_id, is_active) WHERE is_active = true;
CREATE INDEX file_permissions_group_lookup_idx ON file_permissions (granted_to_group_id, is_active) WHERE is_active = true;

-- User accessible files indexes
CREATE INDEX user_accessible_files_user_idx ON user_accessible_files (user_id);
CREATE INDEX user_accessible_files_email_idx ON user_accessible_files (user_email);

-- Conversation indexes
CREATE INDEX conversations_user_activity_idx ON conversations (user_id, last_activity_at DESC) WHERE is_active = true;
CREATE INDEX conversations_lookup_idx ON conversations (conversation_id, user_id);
CREATE INDEX conversations_cleanup_idx ON conversations (updated_at) WHERE is_active = false;

-- Message indexes (for each partition)
CREATE INDEX messages_conversation_time_idx ON messages (conversation_uuid, created_at DESC);
CREATE INDEX messages_role_idx ON messages (role);

-- Delta sync indexes
CREATE INDEX delta_links_status_idx ON delta_links (sync_status, last_sync_at);

-- =============================================================================
-- PERFORMANCE FUNCTIONS
-- =============================================================================

-- Auto-update timestamp function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Efficient vector search with permission filtering
CREATE OR REPLACE FUNCTION search_chunks_with_permissions(
    p_query_embedding vector(384),
    p_user_id TEXT,
    p_user_email TEXT DEFAULT NULL,
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE(
    id BIGINT,
    content TEXT,
    embedding vector(384),
    filename TEXT,
    citation_url TEXT,
    similarity_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        c.id,
        c.content,
        c.embedding,
        c.filename,
        c.citation_url,
        1 - (c.embedding <=> p_query_embedding) as similarity_score
    FROM chunks c
    INNER JOIN user_accessible_files uaf ON c.file_id = uaf.file_id
    WHERE (uaf.user_id = p_user_id OR uaf.user_email = COALESCE(p_user_email, p_user_id))
    ORDER BY c.embedding <=> p_query_embedding
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Efficient conversation history retrieval
CREATE OR REPLACE FUNCTION get_conversation_history_optimized(
    p_conversation_id TEXT,
    p_user_id TEXT,
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE(
    role TEXT,
    content TEXT,
    created_at TIMESTAMP WITH TIME ZONE
) AS $$
DECLARE
    conv_uuid UUID;
BEGIN
    -- Get conversation UUID efficiently
    SELECT id INTO conv_uuid
    FROM conversations 
    WHERE conversation_id = p_conversation_id 
      AND user_id = p_user_id 
      AND is_active = true;
    
    IF conv_uuid IS NULL THEN
        RETURN;
    END IF;
    
    -- Return recent messages
    RETURN QUERY
    SELECT m.role, m.content, m.created_at
    FROM messages m
    WHERE m.conversation_uuid = conv_uuid
    ORDER BY m.created_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Refresh user accessible files (call after permission changes)
CREATE OR REPLACE FUNCTION refresh_user_accessible_files()
RETURNS INTEGER AS $$
DECLARE
    inserted_count INTEGER;
BEGIN
    -- Clear existing data
    TRUNCATE user_accessible_files;
    
    -- Rebuild from current permissions
    INSERT INTO user_accessible_files (file_id, user_id, user_email, access_type, role_name)
    SELECT DISTINCT
        fp.file_id,
        COALESCE(fp.granted_to_user_id, fp.granted_to_user_email) as user_id,
        fp.granted_to_user_email,
        CASE 
            WHEN fp.granted_to_user_id IS NOT NULL THEN 'direct'
            WHEN fp.granted_to_group_id IS NOT NULL THEN 'group'
            WHEN fp.permission_type = 'link' THEN 'link'
            ELSE 'other'
        END as access_type,
        fp.role_name
    FROM file_permissions fp
    WHERE fp.is_active = true
      AND (fp.expires_at IS NULL OR fp.expires_at > CURRENT_TIMESTAMP)
      AND (
          fp.granted_to_user_id IS NOT NULL 
          OR fp.granted_to_user_email IS NOT NULL
          OR fp.permission_type = 'link'
      );
    
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    RETURN inserted_count;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Auto-update timestamps
CREATE TRIGGER update_chunks_updated_at 
    BEFORE UPDATE ON chunks 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_file_permissions_updated_at 
    BEFORE UPDATE ON file_permissions 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_conversations_updated_at 
    BEFORE UPDATE ON conversations 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_delta_links_updated_at 
    BEFORE UPDATE ON delta_links 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Auto-update conversation activity
CREATE OR REPLACE FUNCTION update_conversation_activity()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversations 
    SET last_activity_at = CURRENT_TIMESTAMP 
    WHERE id = NEW.conversation_uuid;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_conversation_activity_trigger
    AFTER INSERT ON messages
    FOR EACH ROW
    EXECUTE FUNCTION update_conversation_activity();

-- =============================================================================
-- PERFORMANCE CONFIGURATION
-- =============================================================================

-- Optimize for your workload (adjust based on your server specs)
-- These are safe defaults for most setups

-- Vector index optimization
ALTER TABLE chunks SET (
    parallel_workers = 4,
    autovacuum_vacuum_scale_factor = 0.1,
    autovacuum_analyze_scale_factor = 0.05
);

-- Enable auto-explain for slow queries
-- ALTER SYSTEM SET auto_explain.log_min_duration = 1000;
-- ALTER SYSTEM SET auto_explain.log_analyze = true;

-- =============================================================================
-- SAMPLE DATA FOR TESTING
-- =============================================================================

-- Insert sample conversations and messages
DO $$
DECLARE
    conv_uuid UUID;
BEGIN
    -- Sample conversation
    INSERT INTO conversations (user_id, conversation_id, channel_id)
    VALUES ('test_user@company.com', 'test_conversation_1', 'test_channel')
    RETURNING id INTO conv_uuid;
    
    -- Sample messages
    INSERT INTO messages (conversation_uuid, role, content, tokens_used, model_used, response_time_ms)
    VALUES 
        (conv_uuid, 'user', 'Hello, can you help me find documents about Azure?', 15, 'gpt-3.5-turbo', 150),
        (conv_uuid, 'assistant', 'I can help you find Azure-related documents. Let me search for you.', 20, 'gpt-3.5-turbo', 800);
END $$;

-- Sample file permissions (replace with your actual data)
INSERT INTO file_permissions (
    file_id, drive_id, filename, permission_id, permission_type, 
    role_name, granted_to_user_id, granted_to_user_email, is_active
) VALUES 
    ('file_123', 'drive_456', 'Azure_Guide.pdf', 'perm_1', 'user', 'read', 'test_user@company.com', 'test_user@company.com', true),
    ('file_124', 'drive_456', 'Teams_Integration.docx', 'perm_2', 'user', 'read', 'test_user@company.com', 'test_user@company.com', true);

-- Refresh user accessible files
SELECT refresh_user_accessible_files();

-- Sample chunks (replace with your actual data)
INSERT INTO chunks (content, embedding, file_id, filename, citation_url, chunk_index, word_count)
VALUES 
    (
        'Azure Functions is a serverless computing service that allows you to run code without managing infrastructure.',
        '[0.1,0.2,0.3,0.4,0.5]'::vector,  -- Replace with real embeddings
        'file_123',
        'Azure_Guide.pdf',
        'https://company.sharepoint.com/Azure_Guide.pdf',
        1,
        15
    ),
    (
        'Microsoft Teams integration enables bots to interact with users in channels and direct messages.',
        '[0.4,0.5,0.6,0.7,0.8]'::vector,  -- Replace with real embeddings
        'file_124',
        'Teams_Integration.docx',
        'https://company.sharepoint.com/Teams_Integration.docx',
        1,
        14
    );

-- =============================================================================
-- MAINTENANCE PROCEDURES
-- =============================================================================

-- Create monthly partition function (call from scheduled job)
CREATE OR REPLACE FUNCTION create_monthly_partition(partition_date DATE)
RETURNS TEXT AS $$
DECLARE
    partition_name TEXT;
    start_date TEXT;
    end_date TEXT;
BEGIN
    partition_name := 'messages_' || to_char(partition_date, 'YYYY_MM');
    start_date := to_char(partition_date, 'YYYY-MM-01');
    end_date := to_char(partition_date + INTERVAL '1 month', 'YYYY-MM-01');
    
    EXECUTE format('CREATE TABLE IF NOT EXISTS %I PARTITION OF messages
                    FOR VALUES FROM (%L) TO (%L)',
                   partition_name, start_date, end_date);
    
    RETURN 'Created partition: ' || partition_name;
END;
$$ LANGUAGE plpgsql;

-- Cleanup old data function
CREATE OR REPLACE FUNCTION cleanup_old_data(days_to_keep INTEGER DEFAULT 90)
RETURNS TEXT AS $$
DECLARE
    deleted_conversations INTEGER;
    deleted_messages INTEGER;
BEGIN
    -- Delete old inactive conversations
    DELETE FROM conversations 
    WHERE is_active = false 
      AND updated_at < CURRENT_TIMESTAMP - INTERVAL '1 day' * days_to_keep;
    
    GET DIAGNOSTICS deleted_conversations = ROW_COUNT;
    
    -- Note: Messages will be deleted automatically due to CASCADE
    
    RETURN format('Cleaned up %s old conversations', deleted_conversations);
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- MONITORING VIEWS
-- =============================================================================

-- Performance monitoring view
CREATE VIEW performance_stats AS
SELECT 
    'chunks' as table_name,
    COUNT(*) as row_count,
    pg_size_pretty(pg_total_relation_size('chunks')) as total_size,
    pg_size_pretty(pg_relation_size('chunks')) as table_size
FROM chunks
UNION ALL
SELECT 
    'file_permissions',
    COUNT(*),
    pg_size_pretty(pg_total_relation_size('file_permissions')),
    pg_size_pretty(pg_relation_size('file_permissions'))
FROM file_permissions
UNION ALL
SELECT 
    'conversations',
    COUNT(*),
    pg_size_pretty(pg_total_relation_size('conversations')),
    pg_size_pretty(pg_relation_size('conversations'))
FROM conversations
UNION ALL
SELECT 
    'messages',
    COUNT(*),
    pg_size_pretty(pg_total_relation_size('messages')),
    pg_size_pretty(pg_relation_size('messages'))
FROM messages;

-- Index usage monitoring
CREATE VIEW index_usage_stats AS
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_stat_user_indexes 
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;

COMMENT ON SCHEMA public IS 'Optimized RAG Bot Database - Production Ready';

-- Final statistics update
ANALYZE;