# Agent Research Empty Evidence Investigation

**Date:** 2026-01-05  
**Issue:** Agent Research section returning empty evidence in LoadRouter app

## Executive Summary

The agent service is **functioning correctly** and returning evidence when tested directly. However, several potential issues were identified that could cause empty evidence in specific scenarios:

1. **Timeout Issue**: Agent timeout is 30 seconds, but actual runs can take 3+ minutes
2. **Missing Property IDs**: If a lead has no property_ids, DB evidence won't be collected
3. **GA SOS Name Matching**: Normalization and matching logic may fail for certain business names
4. **Error Handling**: Silent failures in evidence collection nodes

## Investigation Results

### 1. UI → Backend → Agent Flow ✅ VERIFIED

- **UI Call**: `POST /leads/{lead_id}/agent-intel/run` ✅
- **Backend URL**: `http://localhost:8088` ✅ (from `AI_AGENT_URL` env var, defaults to localhost:8088)
- **Agent Endpoint**: `POST /run` ✅
- **Response Structure**: Correct ✅

### 2. Manual Agent Test ✅ WORKING

Tested with curl:
```bash
curl -X POST http://localhost:8088/run \
  -H "Content-Type: application/json" \
  -d '{"business_name": "CCI CORPORATE SERVICES, INC.", "state": "GA", "property_ids": ["206331738"]}'
```

**Result**: Agent returned evidence successfully:
- 1 DB evidence item
- 1 GA SOS evidence item  
- 17 web evidence items
- 1 places evidence item

**Note**: Request took ~3 minutes, exceeding the 30-second timeout configured in the main app.

### 3. Database Verification ✅

- Sample lead found: ID=1, Owner="CCI CORPORATE SERVICES, INC.", Property IDs=["206331738"]
- GA SOS tables exist: `biz_entity`, `biz_entity_registered_agents`
- Property table accessible with `propertyid::text = ANY(%s)` query (cast issue previously fixed)

### 4. Code Analysis Findings

#### Potential Issues Identified:

1. **Timeout Mismatch** (`routers/lead_agent_intel.py:22`)
   - Current: `AI_AGENT_TIMEOUT = 30` seconds
   - Actual: Agent runs can take 3+ minutes
   - **Impact**: Requests may timeout before evidence is collected

2. **Empty Property IDs** (`ai_agent/src/ai_agent/tools/db.py:54`)
   - If `property_ids` is `None` or empty, no DB evidence is collected
   - No warning logged when this happens
   - **Impact**: Leads without property_ids get no DB evidence

3. **GA SOS Lookup Failures** (`ai_agent/src/ai_agent/tools/ga_sos.py`)
   - Silent failures in exception handling (returns empty list)
   - Name normalization may not match for all business name formats
   - **Impact**: GA SOS evidence may be missing without clear indication

4. **Evidence Accumulation** (`ai_agent/src/ai_agent/graph.py`)
   - Evidence is accumulated across nodes correctly
   - However, if all nodes fail silently, final evidence will be empty

## Fixes Applied

### 1. Enhanced Logging

Added comprehensive logging to track evidence collection:

**Backend (`routers/lead_agent_intel.py`)**:
- Logs payload sent to agent
- Logs response received (evidence count, audit steps)
- Logs full response in debug mode

**Agent Tools**:
- **DB Tool** (`ai_agent/src/ai_agent/tools/db.py`):
  - Logs property_ids, business_name, state
  - Logs number of rows returned
  - Warns when no property_ids provided

- **GA SOS Tool** (`ai_agent/src/ai_agent/tools/ga_sos.py`):
  - Logs business_name and search candidates
  - Logs query patterns and row counts
  - Logs match scores and final results

**Graph Nodes** (`ai_agent/src/ai_agent/graph.py`):
- Logs evidence count at each node
- Logs total evidence accumulation
- Logs final evidence count in build_response

### 2. Improved Error Handling

- Added exception logging with stack traces
- Added warnings for missing data (e.g., no property_ids)
- Better error messages in audit trail

## Recommended Fixes

### Critical: Increase Timeout

**File**: `routers/lead_agent_intel.py`

```python
AI_AGENT_TIMEOUT = int(os.getenv("AI_AGENT_TIMEOUT", "300"))  # 5 minutes instead of 30 seconds
```

**Rationale**: Agent runs can take 3+ minutes. Current 30-second timeout causes premature failures.

### High Priority: Handle Empty Property IDs

**File**: `ai_agent/src/ai_agent/tools/db.py`

Already added logging, but consider:
- Adding a note in the response when property_ids are missing
- Documenting this limitation

### Medium Priority: GA SOS Name Matching

**File**: `ai_agent/src/ai_agent/tools/ga_sos.py`

Consider:
- Expanding normalization patterns
- Adding fuzzy matching for close matches
- Returning partial matches with lower confidence

### Low Priority: Performance Optimization

- Consider parallelizing evidence collection nodes
- Cache GA SOS lookups
- Optimize web search queries

## Testing Recommendations

1. **Test with Various Lead Types**:
   - Lead with property_ids ✅
   - Lead without property_ids
   - Lead with unusual business name formats
   - Lead with no GA SOS matches

2. **Monitor Logs**:
   - Check backend logs for payload/response
   - Check agent logs for evidence collection at each node
   - Verify evidence counts match expectations

3. **Test Timeout Scenarios**:
   - Run with current 30s timeout (should fail)
   - Run with increased timeout (should succeed)

## Diagnosis Steps for Future Issues

1. **Check Backend Logs**:
   ```bash
   # Look for:
   # "Agent intel request for lead_id=X"
   # "Agent intel response for lead_id=X: evidence_count=Y"
   ```

2. **Check Agent Logs**:
   ```bash
   docker logs <agent_container> | grep -E "(load_from_db|lookup_ga_sos|web_evidence|lookup_places|build_response)"
   ```

3. **Verify Payload**:
   - Check `request_payload` in `lead_agent_intel` table
   - Verify `business_name`, `state`, `property_ids` are correct

4. **Verify Response**:
   - Check `response_payload` in `lead_agent_intel` table
   - Verify `evidence` array is populated
   - Check `audit.steps` for node execution

5. **Test Agent Directly**:
   ```bash
   curl -X POST http://localhost:8088/run \
     -H "Content-Type: application/json" \
     -d '{"business_name": "...", "state": "GA", "property_ids": ["..."]}'
   ```

## Root Cause Analysis

Based on investigation, the most likely causes of empty evidence are:

1. **Timeout (Most Likely)**: 30-second timeout is too short for 3+ minute agent runs
2. **Missing Property IDs**: Leads without property_ids won't get DB evidence
3. **GA SOS Matching Failures**: Business name normalization may not match database records
4. **Silent Failures**: Exceptions in evidence collection nodes are caught but not logged clearly

## Next Steps

1. ✅ **Completed**: Added comprehensive logging
2. ⏳ **Pending**: Increase timeout to 300 seconds
3. ⏳ **Pending**: Test with various lead scenarios
4. ⏳ **Pending**: Monitor production logs for patterns

## Files Modified

1. `routers/lead_agent_intel.py` - Added request/response logging
2. `ai_agent/src/ai_agent/tools/db.py` - Added DB lookup logging
3. `ai_agent/src/ai_agent/tools/ga_sos.py` - Added GA SOS lookup logging
4. `ai_agent/src/ai_agent/graph.py` - Added evidence accumulation logging

## Verification

To verify the fixes are working:

1. Run agent intel for a lead with known data
2. Check logs for evidence counts at each stage
3. Verify UI displays evidence correctly
4. Check database `lead_agent_intel` table for stored response

