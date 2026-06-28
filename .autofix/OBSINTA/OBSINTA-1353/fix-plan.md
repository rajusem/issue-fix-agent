## Fix Plan for OBSINTA-1353

### Version
Plan v1 | Iteration 0 (initial draft)

### Root Cause
Evaluation data is validated twice: first in `DataValidator.load_evaluation_data()` (validator.py:142) which calls `validate_evaluation_data()`, and second in `EvaluationPipeline.run_evaluation()` (pipeline.py:141) which calls `self.validate_data()`. This duplicate validation creates unnecessary overhead.

### Approach
Remove the redundant `validate_data()` call in `EvaluationPipeline.run_evaluation()` since the data has already been validated by `DataValidator.load_evaluation_data()` before being passed to the pipeline. The pipeline receives pre-validated data.

### Alternatives Considered
| # | Approach | Pros | Cons | Why Not |
|---|----------|------|------|---------|
| 1 | Remove validation in runner | Simpler pipeline | Runner loses explicit validation feedback | Data is already validated, no need to keep redundant call |
| 2 | Add flag to skip pipeline validation | Minimal change | Adds complexity/flag management | Over-engineered for simple redundancy issue |
| 3 | **Remove validation in pipeline (selected)** | Cleanest solution, no flags | None - data is already validated | Best approach - removes unnecessary work |

### Files to Change
| File | Change | Reason |
|------|--------|--------|
| `src/lightspeed_evaluation/pipeline/evaluation/pipeline.py` | Remove lines 139-142 (the `validate_data()` call) | Data is already validated in `DataValidator.load_evaluation_data()` before being passed to the pipeline |

### Dependencies & Side Effects
- [ ] Public API change? No
- [ ] Config / env var change? No
- [ ] Database migration? No
- [ ] Downstream consumer impact? No - pipeline receives already-validated data
- [ ] Error handling / logging change? No
- [ ] Performance characteristics change? Yes - removes duplicate validation (improvement)

### Risk Assessment
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Validation regression | LOW | HIGH | Data is already validated before pipeline; this is just removing the redundant call |

### Test Strategy
- Existing tests to verify: `tests/unit/pipeline/evaluation/test_pipeline.py` - verify pipeline still works with pre-validated data
- New regression test: Not needed - existing tests cover pipeline functionality

### Confidence
| Dimension | Score | Proof |
|-----------|-------|-------|
| Root cause certainty | HIGH | Code trace: runner calls `load_evaluation_data()` → validates → passes to pipeline → pipeline calls `validate_data()` again |
| Approach correctness | HIGH | Removing redundant validation is safe - data enters pipeline already validated |
| Scope completeness | HIGH | Single file change, minimal scope |

### Investigation Strategy
**Signals detected**: regression
**Strategy used**: Standard investigation (grep + code trace)
**Key findings from strategy**:
  - Found `DataValidator.load_evaluation_data()` at runner/evaluation.py:58
  - Found duplicate `self.validate_data()` call at pipeline/evaluation/pipeline.py:141
  - Both use the same `DataValidator.validate_evaluation_data()` method