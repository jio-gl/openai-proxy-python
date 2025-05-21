import time
import logging
import asyncio

class TokenRateLimiter:
    """Rate limiter for token usage"""
    
    def __init__(self, tpm_limit: int = 30000):
        self.tpm_limit = tpm_limit  # tokens per minute limit
        self.window_size = 60  # seconds
        self.token_usage = []  # List of (timestamp, tokens) tuples
        self.logger = logging.getLogger("api-firewall")
    
    async def check_token_limit(self, requested_tokens: int) -> bool:
        """
        Check if the token request would exceed the rate limit.
        If it would exceed, calculate and wait for the appropriate time.
        Returns True if request can proceed, False if it should be rejected.
        """
        current_time = time.time()
        
        # Remove entries older than the window size
        self.token_usage = [(t, tokens) for t, tokens in self.token_usage if current_time - t < self.window_size]
        
        # Calculate current token usage in the window
        current_usage = sum(tokens for _, tokens in self.token_usage)
        
        # If adding these tokens would exceed the limit
        if current_usage + requested_tokens > self.tpm_limit:
            # Calculate how long to wait
            oldest_time = self.token_usage[0][0] if self.token_usage else current_time
            wait_time = oldest_time + self.window_size - current_time
            
            if wait_time > 0:
                self.logger.warning(f"TPM limit would be exceeded. Current usage: {current_usage}, Requested: {requested_tokens}, Limit: {self.tpm_limit}")
                self.logger.info(f"Waiting {wait_time:.2f} seconds for token limit window to reset")
                await asyncio.sleep(wait_time)
                # After waiting, recursively check again as the window has shifted
                return await self.check_token_limit(requested_tokens)
            
        # Add the new token usage
        self.token_usage.append((current_time, requested_tokens))
        return True 