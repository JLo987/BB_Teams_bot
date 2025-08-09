"""
Conversation history management for the RAG bot.
Handles storing and retrieving conversation context.
"""

import psycopg2
import logging
import os
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import time

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

class ConversationManager:
    def __init__(self):
        self.connection_params = {
            'host': DB_HOST,
            'dbname': DB_NAME,
            'user': DB_USER,
            'password': DB_PASS,
            'sslmode': 'require' if 'azure' in (DB_HOST or '') else 'prefer'
        }
    
    def get_connection(self):
        """Get database connection"""
        return psycopg2.connect(**self.connection_params)
    
    def get_or_create_conversation(self, teams_conversation_id: str, user_id: str, channel_id: str = None, tenant_id: str = None) -> str:
        """Get existing conversation UUID or create new one with optimized structure"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Try to get existing conversation
            cursor.execute(
                "SELECT id FROM conversations_v2 WHERE conversation_id = %s AND user_id = %s AND is_active = true",
                (teams_conversation_id, user_id)
            )
            result = cursor.fetchone()
            
            if result:
                conversation_uuid = result[0]
                # Update the last_activity_at timestamp (triggers automatic updated_at update)
                cursor.execute(
                    "UPDATE conversations_v2 SET last_activity_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (conversation_uuid,)
                )
            else:
                # Create new conversation using optimized structure
                cursor.execute(
                    """INSERT INTO conversations_v2 (conversation_id, user_id, channel_id, tenant_id, is_active) 
                       VALUES (%s, %s, %s, %s, true) RETURNING id""",
                    (teams_conversation_id, user_id, channel_id, tenant_id)
                )
                conversation_uuid = cursor.fetchone()[0]
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return str(conversation_uuid)
            
        except Exception as e:
            logging.error(f"Error managing conversation: {str(e)}")
            return None
    
    def add_message(self, conversation_uuid: str, role: str, content: str, message_id: str = None, 
                   tokens_used: int = None, model_used: str = None, response_time_ms: int = None) -> bool:
        """Add a message to the conversation history with performance tracking"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Insert message using optimized structure with performance tracking
            cursor.execute(
                """INSERT INTO messages_v2 (conversation_uuid, role, content, message_id, tokens_used, model_used, response_time_ms) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (conversation_uuid, role, content, message_id, tokens_used, model_used, response_time_ms)
            )
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return True
            
        except Exception as e:
            logging.error(f"Error adding message: {str(e)}")
            return False
    
    def get_conversation_history(self, conversation_uuid: str, limit: int = 10) -> List[Dict]:
        """Get recent conversation history with performance data"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Enhanced query to include performance metrics
            cursor.execute(
                """SELECT role, content, created_at, tokens_used, model_used, response_time_ms
                   FROM messages_v2 
                   WHERE conversation_uuid = %s 
                   ORDER BY created_at DESC 
                   LIMIT %s""",
                (conversation_uuid, limit)
            )
            
            messages = cursor.fetchall()
            cursor.close()
            conn.close()
            
            # Return in chronological order (oldest first) with performance data
            history = []
            for role, content, created_at, tokens_used, model_used, response_time_ms in reversed(messages):
                history.append({
                    'role': role,
                    'content': content,
                    'timestamp': created_at,
                    'tokens_used': tokens_used,
                    'model_used': model_used,
                    'response_time_ms': response_time_ms
                })
            
            return history
            
        except Exception as e:
            logging.error(f"Error getting conversation history: {str(e)}")
            return []
    
    def get_conversation_context(self, teams_conversation_id: str, user_id: str, limit: int = 6) -> str:
        """Get formatted conversation context for LLM prompt using optimized function"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Use optimized conversation history function
            cursor.execute(
                "SELECT role, content, created_at FROM get_conversation_history_optimized(%s, %s, %s)",
                (teams_conversation_id, user_id, limit)
            )
            
            messages = cursor.fetchall()
            cursor.close()
            conn.close()
            
            if not messages:
                return ""
            
            # Format context (oldest first - reverse the DESC order from function)
            context_parts = []
            for role, content, created_at in reversed(messages):
                if role == 'user':
                    context_parts.append(f"User: {content}")
                else:
                    context_parts.append(f"Assistant: {content}")
            
            return "\n".join(context_parts)
            
        except Exception as e:
            logging.error(f"Error getting conversation context: {str(e)}")
            # Fallback to manual query if optimized function doesn't exist yet
            return self._get_conversation_context_fallback(teams_conversation_id, user_id, limit)
    
    def cleanup_old_messages(self, conversation_uuid: str, keep_last: int = 20) -> bool:
        """Keep only the most recent messages to prevent context from growing too large (optimized for partitioned table)"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # For partitioned table, we need to work with the composite primary key (id, created_at)
            cursor.execute(
                """DELETE FROM messages_v2 
                   WHERE conversation_uuid = %s 
                   AND (id, created_at) NOT IN (
                       SELECT id, created_at FROM messages_v2 
                       WHERE conversation_uuid = %s 
                       ORDER BY created_at DESC 
                       LIMIT %s
                   )""",
                (conversation_uuid, conversation_uuid, keep_last)
            )
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return True
            
        except Exception as e:
            logging.error(f"Error cleaning up messages: {str(e)}")
            return False
    
    def _get_conversation_context_fallback(self, teams_conversation_id: str, user_id: str, limit: int = 6) -> str:
        """Fallback method for getting conversation context if optimized function doesn't exist"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Get conversation UUID
            cursor.execute(
                "SELECT id FROM conversations_v2 WHERE conversation_id = %s AND user_id = %s AND is_active = true",
                (teams_conversation_id, user_id)
            )
            result = cursor.fetchone()
            
            if not result:
                return ""
            
            conversation_uuid = result[0]
            
            # Get recent messages
            cursor.execute(
                """SELECT role, content, created_at 
                   FROM messages 
                   WHERE conversation_uuid = %s 
                   ORDER BY created_at DESC 
                   LIMIT %s""",
                (conversation_uuid, limit)
            )
            
            messages = cursor.fetchall()
            cursor.close()
            conn.close()
            
            if not messages:
                return ""
            
            # Format context (oldest first)
            context_parts = []
            for role, content, created_at in reversed(messages):
                if role == 'user':
                    context_parts.append(f"User: {content}")
                else:
                    context_parts.append(f"Assistant: {content}")
            
            return "\n".join(context_parts)
            
        except Exception as e:
            logging.error(f"Error in fallback conversation context: {str(e)}")
            return ""
    
    def add_message_with_timing(self, conversation_uuid: str, role: str, content: str, 
                               model_used: str = None, start_time: float = None) -> bool:
        """Add message with automatic response time calculation"""
        response_time_ms = None
        if start_time:
            response_time_ms = int((time.time() - start_time) * 1000)
        
        # Estimate token count (rough approximation: 1 token ≈ 4 characters)
        tokens_used = len(content) // 4 if content else 0
        
        return self.add_message(
            conversation_uuid=conversation_uuid,
            role=role,
            content=content,
            tokens_used=tokens_used,
            model_used=model_used,
            response_time_ms=response_time_ms
        )
    
    def get_conversation_stats(self, conversation_uuid: str) -> Dict:
        """Get conversation statistics using optimized structure"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Get conversation stats
            cursor.execute(
                """SELECT 
                    COUNT(*) as message_count,
                    SUM(tokens_used) as total_tokens,
                    AVG(response_time_ms) as avg_response_time,
                    COUNT(DISTINCT model_used) as models_used,
                    MIN(created_at) as first_message,
                    MAX(created_at) as last_message
                   FROM messages_v2 
                   WHERE conversation_uuid = %s""",
                (conversation_uuid,)
            )
            
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                return {
                    'message_count': result[0] or 0,
                    'total_tokens': result[1] or 0,
                    'avg_response_time_ms': float(result[2]) if result[2] else 0,
                    'models_used': result[3] or 0,
                    'first_message': result[4],
                    'last_message': result[5]
                }
            
            return {}
            
        except Exception as e:
            logging.error(f"Error getting conversation stats: {str(e)}")
            return {}
    
    def deactivate_conversation(self, teams_conversation_id: str, user_id: str) -> bool:
        """Soft delete conversation by marking it inactive"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "UPDATE conversations_v2 SET is_active = false WHERE conversation_id = %s AND user_id = %s",
                (teams_conversation_id, user_id)
            )
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return True
            
        except Exception as e:
            logging.error(f"Error deactivating conversation: {str(e)}")
            return False

# Global instance
conversation_manager = ConversationManager() 