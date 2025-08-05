-- RAG Bot Database Schema
-- Creates the necessary table and indexes for document chunks

-- Enable the pgvector extension for vector operations
CREATE EXTENSION IF NOT EXISTS vector;

-- Create the chunks table
CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector(384), -- all-MiniLM-L6-v2 produces 384-dimensional embeddings
    citation_url TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create conversations table to track different chat sessions
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL, -- Teams user ID
    conversation_id TEXT NOT NULL, -- Teams conversation ID
    channel_id TEXT, -- Teams channel ID (null for direct messages)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(conversation_id, user_id)
);

-- Create messages table to store conversation history
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_uuid UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    message_id TEXT, -- Teams message ID (null for assistant messages)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_content_idx ON chunks USING gin(to_tsvector('english', content));
CREATE INDEX IF NOT EXISTS chunks_citation_url_idx ON chunks(citation_url);
CREATE INDEX IF NOT EXISTS chunks_created_at_idx ON chunks(created_at);

-- Conversation indexes
CREATE INDEX IF NOT EXISTS conversations_user_id_idx ON conversations(user_id);
CREATE INDEX IF NOT EXISTS conversations_conversation_id_idx ON conversations(conversation_id);
CREATE INDEX IF NOT EXISTS conversations_updated_at_idx ON conversations(updated_at);

-- Message indexes
CREATE INDEX IF NOT EXISTS messages_conversation_uuid_idx ON messages(conversation_uuid);
CREATE INDEX IF NOT EXISTS messages_created_at_idx ON messages(created_at);
CREATE INDEX IF NOT EXISTS messages_role_idx ON messages(role);

-- Create a function to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers to automatically update updated_at
CREATE TRIGGER update_chunks_updated_at 
    BEFORE UPDATE ON chunks 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_conversations_updated_at 
    BEFORE UPDATE ON conversations 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Function to get recent conversation history
CREATE OR REPLACE FUNCTION get_conversation_history(
    p_conversation_id TEXT,
    p_user_id TEXT,
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE(
    role TEXT,
    content TEXT,
    created_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT m.role, m.content, m.created_at
    FROM messages m
    JOIN conversations c ON m.conversation_uuid = c.id
    WHERE c.conversation_id = p_conversation_id 
      AND c.user_id = p_user_id
    ORDER BY m.created_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Function to cleanup old conversations (optional - for maintenance)
CREATE OR REPLACE FUNCTION cleanup_old_conversations(days_old INTEGER DEFAULT 30)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM conversations 
    WHERE updated_at < NOW() - INTERVAL '1 day' * days_old;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Create file_permissions table to store file access permissions
CREATE TABLE IF NOT EXISTS file_permissions (
    id SERIAL PRIMARY KEY,
    file_id TEXT NOT NULL, -- OneDrive file ID
    drive_id TEXT NOT NULL, -- OneDrive drive ID
    filename TEXT NOT NULL, -- File name for reference
    permission_id TEXT NOT NULL, -- Microsoft Graph permission ID
    permission_type TEXT, -- user, group, link, etc.
    role_name TEXT, -- read, write, owner, etc.
    granted_to_user_id TEXT, -- User ID if granted to a user
    granted_to_user_email TEXT, -- User email if available
    granted_to_group_id TEXT, -- Group ID if granted to a group
    granted_to_group_name TEXT, -- Group name if available
    link_type TEXT, -- view, edit, anonymous, organization (for sharing links)
    link_scope TEXT, -- anonymous, organization, users (for sharing links)
    expires_at TIMESTAMP, -- Expiration date if applicable
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_id, permission_id) -- Prevent duplicate permissions for same file
);

-- Create indexes for efficient permission queries
CREATE INDEX IF NOT EXISTS file_permissions_file_id_idx ON file_permissions(file_id);
CREATE INDEX IF NOT EXISTS file_permissions_drive_id_idx ON file_permissions(drive_id);
CREATE INDEX IF NOT EXISTS file_permissions_user_id_idx ON file_permissions(granted_to_user_id);
CREATE INDEX IF NOT EXISTS file_permissions_group_id_idx ON file_permissions(granted_to_group_id);
CREATE INDEX IF NOT EXISTS file_permissions_updated_at_idx ON file_permissions(updated_at);

-- Create trigger to automatically update updated_at for permissions
CREATE TRIGGER update_file_permissions_updated_at 
    BEFORE UPDATE ON file_permissions 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Insert some sample data for testing
INSERT INTO chunks (content, embedding, citation_url) VALUES 
('This is a sample document about Azure Functions and serverless computing.', 
 '[0.1, 0.2, 0.3]'::vector, 
 'https://docs.microsoft.com/azure-functions'),
('Microsoft Teams integration allows bots to interact with users in channels.', 
 '[0.4, 0.5, 0.6]'::vector, 
 'https://docs.microsoft.com/microsoftteams/bots'); 