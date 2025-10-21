-- Test adding a compound index for the hourly bandwidth query
-- This would help GROUP BY operations

-- Create a test compound index
CREATE INDEX IF NOT EXISTS idx_device_connections_timestamp_bandwidth 
ON device_connections(timestamp, bandwidth_down_mbps, bandwidth_up_mbps);

-- Analyze the table to update statistics
ANALYZE device_connections;
