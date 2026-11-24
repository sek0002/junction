"""Compose BASE constraints while respecting immutable CDS junction codons."""
import timeit


def mutable_regions(length, preserved):
    """Complement of possibly overlapping 1-based, inclusive preserved regions."""
    regions = []
    cursor = 1
    for start, end in sorted(preserved):
        if start > cursor:
            regions.append((cursor, start - 1))
        cursor = max(cursor, end + 1)
    if cursor <= length:
        regions.append((cursor, length))
    return regions


def optimize_cds(sequence, parameters, preserved):
    import msgspec
    from dnachisel import AvoidRareCodons, DnaOptimizationProblem, Location, NoSolutionError
    from mrnarchitect.optimize.engine import build_constraints_and_objectives, optimize
    from mrnarchitect.optimize.models import (
        OptimizationConfig, OptimizationError, OptimizationFailure,
        OptimizationSolution, OptimizationSuccess,
    )
    from mrnarchitect.sequence import Sequence

    configs = [msgspec.convert(parameters, type=OptimizationConfig)]
    configs.extend(OptimizationConfig(organism=parameters['organism'],
        objective=parameters['objective'], start=start, end=end, enforce_sequence=True)
        for start, end in preserved)
    if not parameters['enable_uridine_depletion'] or not preserved:
        return optimize(Sequence(sequence), configs)

    started = timeit.default_timer()
    constraints, objectives = build_constraints_and_objectives(sequence, configs[0])
    mutable = mutable_regions(len(sequence), preserved)
    # BASE expresses wobble-U depletion as AvoidRareCodons. Localise only this
    # constraint; GC windows, motifs and objectives still cover the complete CDS.
    constraints = [local for spec in constraints for local in (
        [spec.copy_with_changes(location=Location(start - 1, end))
         for start, end in mutable] if isinstance(spec, AvoidRareCodons) else [spec])]
    for config in configs[1:]:
        locked, _ = build_constraints_and_objectives(sequence, config)
        constraints.extend(locked)

    try:
        problem = DnaOptimizationProblem(sequence, constraints=constraints,
            objectives=objectives, logger=None)
        # Match the BASE optimiser defaults without changing its private source.
        problem.max_random_iters = 20000
        problem.mutations_per_iteration = 2
        problem.resolve_constraints()
        problem.optimize()
    except NoSolutionError as error:
        return OptimizationFailure(error=OptimizationError(message=str(error.message),
            constraint=None if error.constraint is None else str(error.constraint),
            summary=str(error.problem.constraints_text_summary())),
            time_in_seconds=timeit.default_timer() - started)
    return OptimizationSuccess(solution=OptimizationSolution(sequence=problem.sequence,
        constraints_summary=problem.constraints_text_summary(),
        objectives_summary=problem.objectives_text_summary()),
        time_in_seconds=timeit.default_timer() - started)
