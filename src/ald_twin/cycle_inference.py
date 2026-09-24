"""log-parameter fitting and numerical rank checks for three positive rates/scales."""

import numpy as np
from scipy.optimize import least_squares

# parameter order everywhere in this module: Gamma, kA, kB
PARAMETER_COUNT = 3

# the two log-parameter steps compared before a fit
COARSE_LOG_STEP = .001
FINE_LOG_STEP = .0005
# largest relative change between the two sensitivity estimates before a fit
MAX_STEP_CHANGE = .005
# stopping tolerances for the full fit and for each profile refit
FIT_TOLERANCE = 1e-10
PROFILE_TOLERANCE = 1e-9


# ---- sensitivities

def log_sensitivity(predict, parameters, step=.0005, indices=(0, 1, 2)):
    """differentiate already scaled observations with respect to log parameters.

    uses a central difference in log space, one column per chosen parameter.
    """
    parameters = np.asarray(parameters, dtype=float)
    if (parameters.shape != (PARAMETER_COUNT,) or not np.isfinite(parameters).all()
            or np.any(parameters <= 0)):
        raise ValueError("Gamma, kA and kB must be positive and finite")
    if not np.isfinite(step) or step <= 0:
        raise ValueError("A positive log-parameter step is required")
    columns = []
    for index in indices:
        shift = np.zeros(PARAMETER_COUNT)
        shift[index] = step
        upper = np.asarray(predict(parameters*np.exp(shift)))
        lower = np.asarray(predict(parameters*np.exp(-shift)))
        columns.append((upper - lower) / (2*step))
    return np.column_stack(columns)


def sensitivity_report(first, second, rank_threshold=1e-4):
    """numerical sensitivity directions. these are not statistical intervals.

    first and second are the same sensitivity matrix at two step sizes. the
    rank comes from the singular values of second.
    """
    first = np.asarray(first)
    second = np.asarray(second)
    if first.shape != second.shape or first.ndim != 2 or first.shape[1] != PARAMETER_COUNT:
        raise ValueError("Sensitivity arrays must have the same shape (observations, 3)")

    # singular values, padded to three when there are fewer observations
    _, singular, directions = np.linalg.svd(second, full_matrices=True)
    singular = np.pad(singular, (0, PARAMETER_COUNT-len(singular)))
    if singular[0] > 0:
        ratios = singular/singular[0]
    else:
        ratios = np.zeros(PARAMETER_COUNT)

    # how much the matrix moved between the two step sizes
    norm = np.linalg.norm(second)
    if norm > 0:
        change = np.linalg.norm(first-second)/norm
    else:
        change = float(np.linalg.norm(first-second))

    return dict(relative_step_change=float(change), singular_values=singular.tolist(),
                singular_ratios=ratios.tolist(), numerical_rank=int(np.sum(ratios > rank_threshold)),
                log_parameter_directions=directions.tolist(), rank_threshold=rank_threshold,
                parameter_order=["Gamma", "kA", "kB"],
                interpretation="Scaled deterministic sensitivities; no observation-noise or statistical claim")


# ---- fitting

def fit_parameters(predict, observations, initial, lower, upper, *, max_evaluations=30):
    """fit only Gamma, kA and kB, with fixed observation scaling and explicit bounds."""
    # check the start point, bounds and observations
    initial = np.asarray(initial, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    for value in (initial, lower, upper):
        if value.shape != (PARAMETER_COUNT,) or not np.isfinite(value).all():
            raise ValueError("Three finite parameters and bounds are required")
    if np.any(lower <= 0) or np.any(lower >= initial) or np.any(initial >= upper):
        raise ValueError("Initial parameters must lie strictly inside positive bounds")
    observations = np.asarray(observations, dtype=float)
    if observations.ndim != 1 or not np.isfinite(observations).all():
        raise ValueError("Finite, scaled observation values are required")

    # refuse to fit unless the sensitivities are stable and full rank
    first = log_sensitivity(predict, initial, COARSE_LOG_STEP)
    second = log_sensitivity(predict, initial, FINE_LOG_STEP)
    prefit = sensitivity_report(first, second)
    if prefit["relative_step_change"] > MAX_STEP_CHANGE or prefit["numerical_rank"] < PARAMETER_COUNT:
        raise ValueError("A stable, full-rank sensitivity check is required before a unique three-parameter fit")

    # fit log factors on the initial values, so the bounds become log bounds
    def residuals(log_factors):
        """model minus observations at initial*exp(log_factors)."""
        return predict(initial*np.exp(log_factors))-observations

    def jacobian(log_factors):
        """log sensitivities at initial*exp(log_factors)."""
        return log_sensitivity(predict, initial*np.exp(log_factors))

    result = least_squares(residuals, np.zeros(PARAMETER_COUNT),
                           bounds=(np.log(lower/initial), np.log(upper/initial)), jac=jacobian,
                           ftol=FIT_TOLERANCE, xtol=FIT_TOLERANCE, gtol=FIT_TOLERANCE,
                           max_nfev=max_evaluations)
    fitted = initial*np.exp(result.x)
    return fitted, dict(success=bool(result.success), status=int(result.status), message=result.message,
                        cost=float(result.cost), optimality=float(result.optimality),
                        evaluations=int(result.nfev), active_bounds=result.active_mask.tolist(),
                        prefit=prefit, residuals=result.fun.tolist(),
                        initial=initial.tolist(), lower=lower.tolist(), upper=upper.tolist())


def parameter_profile(predict, observations, reference, index, factors, lower, upper, max_evaluations=20):
    """fix one parameter and locally refit the other two. no confidence claim."""
    reference = np.asarray(reference, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    if index not in (0, 1, 2) or reference.shape != (PARAMETER_COUNT,):
        raise ValueError("Profile one of Gamma, kA or kB")
    if np.any(lower <= 0) or np.any(lower >= reference) or np.any(reference >= upper):
        raise ValueError("Reference must lie strictly inside positive bounds")

    # the two parameters that are refit at each profile point
    free_columns = []
    for column in range(PARAMETER_COUNT):
        if column != index:
            free_columns.append(column)
    free = np.array(free_columns)

    points = []
    for factor in factors:
        fixed = reference[index]*factor
        if not lower[index] <= fixed <= upper[index]:
            raise ValueError("Fixed profile value is outside its declared bounds")

        def parameters(log_factors):
            """full parameter vector with the fixed value and the free log factors."""
            values = reference.copy()
            values[index] = fixed
            values[free] *= np.exp(log_factors)
            return values

        def residuals(log_factors):
            """model minus observations at this profile point."""
            return predict(parameters(log_factors))-observations

        def jacobian(log_factors):
            """log sensitivities of the two free parameters."""
            return log_sensitivity(predict, parameters(log_factors), indices=free)

        fit = least_squares(residuals, np.zeros(2),
                            bounds=(np.log(lower[free]/reference[free]), np.log(upper[free]/reference[free])),
                            jac=jacobian, tr_solver="lsmr",
                            ftol=PROFILE_TOLERANCE, xtol=PROFILE_TOLERANCE, gtol=PROFILE_TOLERANCE,
                            max_nfev=max_evaluations)
        points.append(dict(factor=float(factor), parameters=parameters(fit.x).tolist(),
                           cost=float(fit.cost), residuals=fit.fun.tolist(), converged=bool(fit.success),
                           optimality=float(fit.optimality), evaluations=int(fit.nfev),
                           active_bounds=fit.active_mask.tolist(), message=fit.message))
    return points
