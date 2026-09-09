"""Log-parameter fitting and numerical rank checks for three positive rates/scales."""

import numpy as np
from scipy.optimize import least_squares


def log_sensitivity(predict, parameters, step=.0005, indices=(0, 1, 2)):
    """Differentiate already scaled observations with respect to log parameters."""
    parameters = np.asarray(parameters, dtype=float)
    if parameters.shape != (3,) or not np.isfinite(parameters).all() or np.any(parameters <= 0):
        raise ValueError("Gamma, kA and kB must be positive and finite")
    if not np.isfinite(step) or step <= 0:
        raise ValueError("A positive log-parameter step is required")
    columns = []
    for index in indices:
        shift = np.zeros(3)
        shift[index] = step
        columns.append((np.asarray(predict(parameters*np.exp(shift)))
                        - np.asarray(predict(parameters*np.exp(-shift)))) / (2*step))
    return np.column_stack(columns)


def sensitivity_report(first, second, rank_threshold=1e-4):
    """Numerical sensitivity directions; these are not statistical intervals."""
    first, second = np.asarray(first), np.asarray(second)
    if first.shape != second.shape or first.ndim != 2 or first.shape[1] != 3:
        raise ValueError("Sensitivity arrays must have the same shape (observations, 3)")
    _, singular, directions = np.linalg.svd(second, full_matrices=True)
    singular = np.pad(singular, (0, 3-len(singular)))
    ratios = singular/singular[0] if singular[0] > 0 else np.zeros(3)
    norm = np.linalg.norm(second)
    change = np.linalg.norm(first-second)/norm if norm > 0 else float(np.linalg.norm(first-second))
    return dict(relative_step_change=float(change), singular_values=singular.tolist(),
                singular_ratios=ratios.tolist(), numerical_rank=int(np.sum(ratios > rank_threshold)),
                log_parameter_directions=directions.tolist(), rank_threshold=rank_threshold,
                parameter_order=["Gamma", "kA", "kB"],
                interpretation="Scaled deterministic sensitivities; no observation-noise or statistical claim")


def fit_parameters(predict, observations, initial, lower, upper, *, max_evaluations=30):
    """Fit only Gamma, kA and kB, with fixed observation scaling and explicit bounds."""
    initial, lower, upper = (np.asarray(value, dtype=float) for value in (initial, lower, upper))
    if any(value.shape != (3,) or not np.isfinite(value).all() for value in (initial, lower, upper)):
        raise ValueError("Three finite parameters and bounds are required")
    if np.any(lower <= 0) or np.any(lower >= initial) or np.any(initial >= upper):
        raise ValueError("Initial parameters must lie strictly inside positive bounds")
    observations = np.asarray(observations, dtype=float)
    if observations.ndim != 1 or not np.isfinite(observations).all():
        raise ValueError("Finite, scaled observation values are required")
    first = log_sensitivity(predict, initial, .001)
    second = log_sensitivity(predict, initial, .0005)
    prefit = sensitivity_report(first, second)
    if prefit["relative_step_change"] > .005 or prefit["numerical_rank"] < 3:
        raise ValueError("A stable, full-rank sensitivity check is required before a unique three-parameter fit")
    result = least_squares(lambda log_factors: predict(initial*np.exp(log_factors))-observations,
                           np.zeros(3), bounds=(np.log(lower/initial), np.log(upper/initial)),
                           jac=lambda log_factors: log_sensitivity(predict, initial*np.exp(log_factors)),
                           ftol=1e-10, xtol=1e-10, gtol=1e-10, max_nfev=max_evaluations)
    fitted = initial*np.exp(result.x)
    return fitted, dict(success=bool(result.success), status=int(result.status), message=result.message,
                        cost=float(result.cost), optimality=float(result.optimality),
                        evaluations=int(result.nfev), active_bounds=result.active_mask.tolist(),
                        prefit=prefit, residuals=result.fun.tolist(),
                        initial=initial.tolist(), lower=lower.tolist(), upper=upper.tolist())


def parameter_profile(predict, observations, reference, index, factors, lower, upper, max_evaluations=20):
    """Fix one parameter and locally refit the other two; no confidence claim."""
    reference, lower, upper = (np.asarray(value, dtype=float) for value in (reference, lower, upper))
    if index not in (0, 1, 2) or reference.shape != (3,):
        raise ValueError("Profile one of Gamma, kA or kB")
    if np.any(lower <= 0) or np.any(lower >= reference) or np.any(reference >= upper):
        raise ValueError("Reference must lie strictly inside positive bounds")
    free = np.array([column for column in range(3) if column != index])
    points = []
    for factor in factors:
        fixed = reference[index]*factor
        if not lower[index] <= fixed <= upper[index]:
            raise ValueError("Fixed profile value is outside its declared bounds")

        def parameters(log_factors):
            values = reference.copy()
            values[index] = fixed
            values[free] *= np.exp(log_factors)
            return values

        fit = least_squares(lambda values: predict(parameters(values))-observations,
                            np.zeros(2), bounds=(np.log(lower[free]/reference[free]), np.log(upper[free]/reference[free])),
                            jac=lambda values: log_sensitivity(predict, parameters(values), indices=free),
                            tr_solver="lsmr", ftol=1e-9, xtol=1e-9, gtol=1e-9, max_nfev=max_evaluations)
        points.append(dict(factor=float(factor), parameters=parameters(fit.x).tolist(),
                           cost=float(fit.cost), residuals=fit.fun.tolist(), converged=bool(fit.success),
                           optimality=float(fit.optimality), evaluations=int(fit.nfev),
                           active_bounds=fit.active_mask.tolist(), message=fit.message))
    return points
