import time
import logging
import asyncio
from typing import List, Tuple

class TokenRateLimiter:
    """Rate limiter for token usage"""
    
    def __init__(self, tpm_limit: int = 30000):
        self.tpm_limit = tpm_limit  # tokens per minute limit
        self.window_size = 60  # seconds
        self.token_usage: List[Tuple[float, int]] = []  # List of (timestamp, tokens) tuples
        self.logger = logging.getLogger("api-firewall")
        self.last_cleanup = time.time()
        self.safety_buffer = 0.95  # Only use 95% of the limit to be safe
    
    def _cleanup_old_entries(self, current_time: float) -> None:
        """Remove entries older than the window size"""
        # Only clean up if it's been at least 1 second since last cleanup
        if current_time - self.last_cleanup >= 1:
            self.token_usage = [(t, tokens) for t, tokens in self.token_usage 
                              if current_time - t < self.window_size]
            self.last_cleanup = current_time
    
    def _calculate_current_usage(self) -> int:
        """Calculate current token usage in the window"""
        return sum(tokens for _, tokens in self.token_usage)
    
    def _calculate_wait_time(self, current_time: float, requested_tokens: int) -> float:
        """Calculate how long to wait before processing the request"""
        if not self.token_usage:
            return 0
            
        current_usage = self._calculate_current_usage()
        effective_limit = int(self.tpm_limit * self.safety_buffer)
        
        if current_usage + requested_tokens <= effective_limit:
            return 0
            
        # Calculate the minimum wait time needed for enough tokens to free up
        tokens_to_free = current_usage + requested_tokens - effective_limit
        oldest_time = self.token_usage[0][0]
        
        # Calculate how many tokens will be freed at different times
        token_timeline = []
        current_total = current_usage
        
        for timestamp, tokens in sorted(self.token_usage):
            time_until_free = timestamp + self.window_size - current_time
            if time_until_free > 0:
                token_timeline.append((time_until_free, tokens))
        
        # Find the minimum wait time that frees up enough tokens
        cumulative_freed = 0
        for wait_time, tokens in sorted(token_timeline):
            cumulative_freed += tokens
            if current_usage - cumulative_freed + requested_tokens <= effective_limit:
                return wait_time + 0.1  # Add a small buffer
        
        # If we can't find a specific time, use the window size
        return self.window_size
    
    async def check_token_limit(self, requested_tokens: int) -> bool:
        """
        Check if the token request would exceed the rate limit.
        If it would exceed, calculate and wait for the appropriate time.
        Returns True if request can proceed, False if it should be rejected.
        """
        current_time = time.time()
        
        # Clean up old entries
        self._cleanup_old_entries(current_time)
        
        # Calculate current usage
        current_usage = self._calculate_current_usage()
        effective_limit = int(self.tpm_limit * self.safety_buffer)
        
        # Log current state
        self.logger.debug(f"Current token usage: {current_usage}/{effective_limit} (requested: {requested_tokens})")
        
        # If adding these tokens would exceed the limit
        if current_usage + requested_tokens > effective_limit:
            wait_time = self._calculate_wait_time(current_time, requested_tokens)
            
            if wait_time > 0:
                self.logger.warning(
                    f"TPM limit would be exceeded. Current usage: {current_usage}, "
                    f"Requested: {requested_tokens}, Limit: {effective_limit}"
                )
                self.logger.info(f"Waiting {wait_time:.2f} seconds for token limit window to reset")
                
                # Wait for the calculated time
                await asyncio.sleep(wait_time)
                
                # After waiting, recursively check again as the window has shifted
                return await self.check_token_limit(requested_tokens)
        
        # Add the new token usage
        self.token_usage.append((current_time, requested_tokens))
        return True 