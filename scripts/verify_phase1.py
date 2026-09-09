"""Run the frozen Phase 1 mathematical acceptance studies, individually or together."""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
from scipy.integrate import solve_ivp

from ald_twin.analytical import cell_averages, pulse_response
from ald_twin.configuration import ParameterRegistry
from ald_twin.numerics import SolverOptions
from ald_twin.reactor_0d import FlowSegment, WellMixedReactor, solve_0d
from ald_twin.reactor_1d import (AdvectiveBoundary, ConcentrationBoundary, FluxBoundary,
    Reactor1D, TransportSegment, face_fluxes, solve_1d)
from ald_twin.surface import FiniteCapacity
from ald_twin.units import (R, actual_volumetric_flow, angstrom_to_metre, celsius_to_kelvin,
    density_g_cm3_to_kg_m3, molar_mass_g_mol_to_kg_mol, sccm_to_molar_flow)
from ald_twin.verification import (ManufacturedSolution, advection_pulse_average,
    dimensional_checks, front_position, normalized_l1, restrict_uniform)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase1"
FIGURES = ROOT / "figures/phase1"
GATE_CATEGORIES = ["units", "analytical cases", "conservation", "state bounds",
    "temporal convergence", "spatial convergence", "independent solver comparison",
    "boundary conditions", "domain truncation", "numerical diffusion"]
GROUPS = ["basic", "transport", "temporal", "spatial", "manufactured", "truncation"]
PARAMETER_UNITS = dict(length="m",area="m^2",reactive_perimeter="m",velocity="m s^-1",
    diffusivity="m^2 s^-1",capacity="mol m^-2",capture_velocity="m s^-1",
    concentration_scale="mol m^-3",inlet_concentration="mol m^-3",initial_c="mol m^-3",
    initial_theta="1",pulse_duration="s",purge_duration="s",duration="s",volume="m^3",
    reactive_area="m^2",throughput="m^3 s^-1",inlet_molar_flow="mol s^-1",decay="s^-1",
    theta_amplitude="1",base_theta="1",base_length="m")


def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ROOT.glob("src/ald_twin/*.py"))}


class Study:
    def __init__(self, group):
        self.group = group
        self.rows, self.runs, self.data, self.configs = [], [], {}, {}
        self.start = time.perf_counter()

    def case(self, name):
        path = ROOT / f"config/synthetic/phase1-{name}.json"
        document = json.loads(path.read_text())
        registry = ParameterRegistry.load(path)
        self.configs[name] = document
        values = registry.resolve({p.name: PARAMETER_UNITS[p.name] for p in registry.parameters})
        return values, document["settings"], registry.identifier+":"+registry.sha256

    def check(self, name, category, error, tolerance, **details):
        error = float(error)
        self.rows.append(dict(name=name, category=category, error=error,
            tolerance=float(tolerance), passed=bool(np.isfinite(error) and error <= tolerance), details=details))

    def record(self, name, result, scale, *, upper_bound=False, source=False):
        denominator = result.metadata["initial_gas_moles"] + result.entered_moles
        if source:
            denominator = denominator + np.abs(result.source_moles)
        mask = denominator > 0
        ledger = float(np.max(np.abs(result.ledger_error_moles[mask])/denominator[mask], initial=0.))
        if np.any(~mask):
            zero_residual = float(np.max(np.abs(result.ledger_error_moles[~mask]), initial=0.))
            self.check(name+" zero-inventory ledger", "conservation", zero_residual, 0.)
        self.check(name+" relative ledger", "conservation", ledger, 1e-8)
        self.check(name+" c lower bound", "state bounds", max(0.,-float(result.c.min())/scale),1e-8)
        self.check(name+" theta bounds", "state bounds", max(0.,-float(result.theta.min()),float(result.theta.max())-1),1e-8)
        if upper_bound:
            self.check(name+" c upper bound", "state bounds", max(0.,float(result.c.max())/scale-1),1e-8)
        self.runs.append(dict(name=name,metadata=result.metadata,
            solver_status=[{k:v for k,v in entry.items() if k not in ("start_state","end_state")}
                           for entry in result.solver_status],
            exact_segment_carryover=all(a["end_state"]==b["start_state"]
                for a,b in zip(result.solver_status,result.solver_status[1:])),
            max_relative_ledger=ledger, final_capture=float(result.captured_moles[-1]),
            max_absolute_ledger=float(np.max(np.abs(result.ledger_error_moles))),
            final_entered=float(result.entered_moles[-1]),final_escaped=float(result.escaped_moles[-1])))
        self.data[name+"_z"] = result.z
        self.data[name+"_c"] = result.c[-1]
        self.data[name+"_theta"] = result.theta[-1]
        self.data[name+"_t"] = result.t
        self.data[name+"_ledger"] = result.ledger_error_moles

    def save(self, extra=None):
        OUT.mkdir(parents=True,exist_ok=True)
        payload = dict(group=self.group,checks=self.rows,runs=self.runs,case_configs=self.configs,
            code_sha256=hashes(),runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            elapsed_seconds=time.perf_counter()-self.start,extra=extra or {})
        (OUT/f"{self.group}.json").write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n")
        np.savez_compressed(OUT/f"{self.group}.npz",**self.data)
        failures=[r for r in self.rows if not r["passed"]]
        print(json.dumps(dict(group=self.group,checks=len(self.rows),failures=failures,
                              elapsed_seconds=payload["elapsed_seconds"])),flush=True)
        return not failures


def options(settings, *, tight=False, method="Radau"):
    prefix="refinement_" if tight else ""
    return SolverOptions(method=method,rtol=settings[prefix+"rtol"],atol=settings[prefix+"atol"],
                         max_step=settings[prefix+"max_step"])


def geometry(parameters, cells):
    return Reactor1D(
        length=parameters["length"], area=parameters["area"],
        reactive_perimeter=parameters["reactive_perimeter"],
        velocity=parameters["velocity"], diffusivity=parameters["diffusivity"], cells=cells)


def pulse_run(parameters, settings, identifier, cells, *,
              boundary="concentration", tight=True, method="Radau"):
    reactor = geometry(parameters, cells)
    surface = FiniteCapacity(parameters["capacity"], parameters["capture_velocity"])
    if boundary == "concentration":
        exposure = ConcentrationBoundary(parameters["inlet_concentration"], 0.)
        purge = ConcentrationBoundary(0., 0.)
    elif boundary == "flux":
        exposure = FluxBoundary(parameters["inlet_molar_flow"])
        purge = FluxBoundary(0.)
    else:
        exposure = AdvectiveBoundary(parameters["inlet_concentration"])
        purge = AdvectiveBoundary(0.)
    segments = [
        TransportSegment(parameters["pulse_duration"], exposure, "exposure"),
        TransportSegment(parameters["purge_duration"], purge, "purge"),
    ]
    return solve_1d(
        reactor, surface, segments,
        concentration_scale=parameters["concentration_scale"],
        initial_c=parameters.get("initial_c", 0.),
        initial_theta=parameters.get("initial_theta", 0.),
        options=options(settings, tight=tight, method=method),
        provenance_id=identifier,
        output_times=np.linspace(
            0, parameters["pulse_duration"] + parameters["purge_duration"],
            settings["output_samples"]),
    )


def check_units(study):
    dimensions=dimensional_checks()
    study.check("exact equation dimensions","units",sum(not x for x in dimensions.values()),0.,equations=dimensions)
    # Independent Decimal arithmetic uses exact declared SI constants/conventions.
    from decimal import Decimal, localcontext
    with localcontext() as ctx:
        ctx.prec=50
        d=Decimal
        expected=float(d("101325")*(d("500")*d("1e-6")/d("60"))/(d("8.31446261815324")*d("273.15")))
    flow=sccm_to_molar_flow(500.,273.15,101325.)
    conversion_errors={"sccm_to_mol_s":abs(flow/expected-1),
        "actual_volume":abs(actual_volumetric_flow(flow,423.15,200.)/
            ((500e-6/60)*(423.15/273.15)*(101325/200))-1),
        "C_to_K":abs(celsius_to_kelvin(150.)/423.15-1),
        "angstrom":abs(angstrom_to_metre(10.)/1e-9-1),
        "density":abs(density_g_cm3_to_kg_m3(5.4)/5400.-1),
        "molar_mass":abs(molar_mass_g_mol_to_kg_mol(72.)/.072-1)}
    for name, error in conversion_errors.items():
        study.check(name, "units", error, 1e-12)


def check_well_mixed_cases(study):
    for case_name in ("zero-0d","purge-0d","closed-batch","pulse-0d"):
        p,s,identifier=study.case(case_name)
        surface=FiniteCapacity(p["capacity"],p["capture_velocity"])
        reactor=WellMixedReactor(p["volume"],p["reactive_area"],p["throughput"])
        initials=s.get("initial_concentrations",[p["initial_c"]])
        for i,c0 in enumerate(initials):
            label=f"{case_name}_{i}"
            segments=([FlowSegment(p["pulse_duration"],p["inlet_molar_flow"]),FlowSegment(p["purge_duration"],0.)]
                if case_name=="pulse-0d" else [FlowSegment(p["duration"],0.)])
            duration=sum(x.duration for x in segments)
            result=solve_0d(reactor,surface,segments,concentration_scale=p["concentration_scale"],
                initial_c=c0,initial_theta=p["initial_theta"],options=options(s),provenance_id=identifier,
                output_times=np.linspace(0,duration,s["output_samples"]))
            study.record(label,result,p["concentration_scale"])
            if case_name=="zero-0d":
                study.check("0D zero gas","analytical cases",np.max(np.abs(result.c))/p["concentration_scale"],1e-10)
                study.check("0D zero-input theta change","analytical cases",np.max(np.abs(result.theta-p["initial_theta"])),1e-10)
            elif case_name=="purge-0d":
                exact=c0*np.exp(-reactor.throughput/ reactor.volume*result.t)
                study.check("0D purge over ten residence times","analytical cases",np.max(np.abs(result.c[:,0]-exact))/c0,1e-7)
                study.data["purge_exact"]=exact
                study.data["purge_actual"]=result.c[:,0]
            elif case_name=="closed-batch":
                inventory=reactor.volume*result.c[:,0]+reactor.reactive_area*surface.capacity*result.theta[:,0]
                target=min(1.,p["initial_theta"]+reactor.volume*c0/(reactor.reactive_area*surface.capacity))
                study.check(label+" total inventory","conservation",np.max(np.abs(inventory-inventory[0]))/inventory[0],1e-8)
                study.check(label+" dose/capacity endpoint","analytical cases",abs(result.theta[-1,0]-target),1e-6)


def check_surface_saturation(study):
    p,s,identifier=study.case("surface-saturation")
    surface=FiniteCapacity(p["capacity"],p["capture_velocity"])
    lam=surface.capture_velocity*p["inlet_concentration"]/surface.capacity
    duration=s["e_folding_times"]/lam
    t=np.linspace(0,duration,s["output_samples"])
    result=solve_ivp(lambda t,y:surface.rate(p["inlet_concentration"],y)/surface.capacity,
        (0,duration),[p["initial_theta"]],method="Radau",rtol=s["rtol"],atol=s["atol"],t_eval=t)
    if not result.success:
        raise RuntimeError(result.message)
    exact=1-(1-p["initial_theta"])*np.exp(-lam*t)
    study.check("prescribed-exposure saturation","analytical cases",np.max(np.abs(result.y[0]-exact)),1e-7)
    study.data.update(saturation_t=t,saturation_actual=result.y[0],saturation_exact=exact)


def basic():
    study = Study("basic")
    check_units(study)
    check_well_mixed_cases(study)
    check_surface_saturation(study)
    p,s,identifier=study.case("reacting-front")
    r=geometry(p,32)
    empty=solve_1d(r,FiniteCapacity(p["capacity"],p["capture_velocity"]),
        [TransportSegment(1.,FluxBoundary(0.))],concentration_scale=1.,initial_theta=.3,
        options=options(s),provenance_id=identifier)
    study.record("zero_1d",empty,1.)
    study.check("1D zero input","analytical cases",max(np.max(np.abs(empty.c)),np.max(np.abs(empty.theta-.3))),1e-10)
    boundary_errors=[]
    for u in (1.,-1.,0.):
        rr=replace(r,velocity=u)
        uniform=solve_1d(rr,FiniteCapacity(1.,0.),[TransportSegment(.3,ConcentrationBoundary(1.,1.))],
            concentration_scale=1.,initial_c=1.,initial_theta=.3,options=options(s),provenance_id=identifier)
        study.record(f"constant_u{u:g}",uniform,1.,upper_bound=True)
        boundary_errors.append(float(np.max(np.abs(uniform.c-1.))))
    study.check("equal fixed boundaries preserve constant solution","boundary conditions",max(boundary_errors),1e-10)
    c=np.linspace(.2,.8,r.cells)
    flux=face_fluxes(c,r,FluxBoundary(.7))
    study.check("prescribed total inlet face flux","boundary conditions",abs(flux[0]-.7/r.area),1e-12)
    study.check("zero downstream diffusive flux","boundary conditions",abs(flux[-1]-r.velocity*c[-1]),1e-12)
    # Reconstruct the imposed face concentrations from diffusion flux; this
    # independently checks half-cell distance and the signed advective donor.
    for u in (1.,-1.):
        rr=replace(r,velocity=u)
        bc=ConcentrationBoundary(.7,.1)
        flux=face_fluxes(c,rr,bc)
        adv_l=u*(bc.left if u>0 else c[0])
        adv_r=u*(c[-1] if u>0 else bc.right)
        left=c[0]+(flux[0]-adv_l)*rr.dz/(2*rr.diffusivity)
        right=c[-1]-(flux[-1]-adv_r)*rr.dz/(2*rr.diffusivity)
        study.check(f"fixed face concentrations u={u:g}","boundary conditions",max(abs(left-bc.left),abs(right-bc.right)),1e-12)
    saturated=solve_1d(r,FiniteCapacity(1.,10.),
        [TransportSegment(.2,FluxBoundary(1.)),TransportSegment(.2,FluxBoundary(0.)),TransportSegment(.2,FluxBoundary(1.))],
        concentration_scale=1.,initial_theta=1.,provenance_id=identifier)
    study.record("repeated_saturated_exposure",saturated,1.)
    study.check("same precursor cannot recapture saturated capacity","analytical cases",np.max(np.abs(saturated.theta-1.)),1e-10)
    return study.save(extra={"unit_reference_convention":{"T_ref_K":273.15,"P_ref_Pa":101325.,
        "status":"assumed arithmetic convention, not author-exact experimental input"}})


def transport(resume=False):
    study=Study("transport")
    histories={}
    prior_acceptance=[]
    previous_elapsed=0.
    if resume:
        old=json.loads((OUT/"transport.json").read_text())
        if old["code_sha256"] != hashes():
            raise ValueError("Cannot reuse transport results after an engine change")
        old_acceptance=[r for r in old["checks"] if r["name"].endswith(" analytical pulse L1")]
        prior_acceptance=old["extra"].get("prior_acceptance",[])+old_acceptance
        study.rows=[r for r in old["checks"] if r not in old_acceptance]
        study.runs=old["runs"]
        study.configs=old["case_configs"].copy()
        with np.load(OUT/"transport.npz") as archive:
            study.data={name:archive[name] for name in archive.files}
        histories=old["extra"]["histories"]
        previous_elapsed=old["elapsed_seconds"]
    for case_name in ("transport-pulse","diffusion-pulse","advection-pulse"):
        previous_config=study.configs.get(case_name)
        p,s,identifier=study.case(case_name)
        entries=histories.get(case_name,[])
        if previous_config is not None:
            current=study.configs[case_name]
            if (current["parameters"] != previous_config["parameters"] or
                {k:v for k,v in current["settings"].items() if k!="grids"} !=
                {k:v for k,v in previous_config["settings"].items() if k!="grids"}):
                raise ValueError("Resumption permits grid extension only, not changed physical or numerical settings")
            old_grids=[e["cells"] for e in entries]
            if s["grids"][:len(old_grids)] != old_grids:
                raise ValueError("Existing grid history must be retained in order")
        for n in s["grids"]:
            if any(e["cells"]==n for e in entries):
                continue
            print(f"{case_name}: {n} cells",flush=True)
            result=pulse_run(p,s,identifier,n,boundary=s["boundary"])
            faces=np.linspace(0,p["length"],n+1)
            if p["diffusivity"]==0:
                exact=advection_pulse_average(faces,result.t[-1],p["pulse_duration"],p["velocity"])
            else:
                exact=cell_averages(lambda z:pulse_response(z,result.t[-1],p["pulse_duration"],p["velocity"],p["diffusivity"]),faces)
            error=normalized_l1(result.c[-1]/p["inlet_concentration"],exact)
            name=f"{case_name}_{n}"
            study.record(name,result,p["concentration_scale"],upper_bound=True)
            study.check(name+" zero reaction theta","analytical cases",np.max(np.abs(result.theta-p["initial_theta"])),1e-10)
            if p["diffusivity"]>0:
                study.check(name+" Dnum/D","numerical diffusion",result.metadata["numerical_diffusivity_ratio"],.05)
            study.data[name+"_exact"]=exact
            entries.append(dict(cells=n,dz=p["length"]/n,error=error))
            print(f"  normalized L1 = {error:.6g}",flush=True)
        study.check(case_name+" analytical pulse L1","analytical cases",entries[-1]["error"],s["final_l1_tolerance"])
        histories[case_name]=entries
    return study.save(extra={"histories":histories,"prior_acceptance":prior_acceptance,
                             "reused_elapsed_seconds":previous_elapsed})


def temporal():
    study=Study("temporal")
    p,s,identifier=study.case("reacting-front")
    results={}
    for method in ("Radau","BDF"):
        for tight in (False,True):
            name=f"{method}_{'tight' if tight else 'base'}"
            print("Temporal "+name,flush=True)
            result=pulse_run(p,s,identifier,s["temporal_cells"],boundary="flux",tight=tight,method=method)
            study.record(name,result,1.)
            results[name]=result
        base,tight=results[f"{method}_base"],results[f"{method}_tight"]
        study.check(method+" temporal theta","temporal convergence",np.max(np.abs(base.theta[-1]-tight.theta[-1])),1e-5)
        study.check(method+" temporal uptake","temporal convergence",abs(base.captured_moles[-1]/tight.captured_moles[-1]-1),1e-5)
    study.check("temporally refined Radau/BDF theta","independent solver comparison",
        np.max(np.abs(results["Radau_tight"].theta[-1]-results["BDF_tight"].theta[-1])),1e-5)
    return study.save()


def spatial():
    study=Study("spatial")
    p,s,identifier=study.case("reacting-front")
    previous=None
    history=[]
    for n in s["grids"]:
        print(f"Reacting spatial grid: {n}",flush=True)
        result=pulse_run(p,s,identifier,n,boundary="flux",tight=True)
        study.record(f"reacting_{n}",result,1.)
        front=front_position(result.z,result.theta[-1],s["front_theta"])
        entry=dict(cells=n,dz=p["length"]/n,front=front,uptake=float(result.captured_moles[-1]))
        study.check(f"reacting {n} Dnum/D","numerical diffusion",result.metadata["numerical_diffusivity_ratio"],.05)
        if previous is not None:
            entry.update(theta_difference=float(np.max(np.abs(restrict_uniform(result.theta[-1],len(previous.z))-previous.theta[-1]))),
                relative_uptake_difference=float(abs(previous.captured_moles[-1]/result.captured_moles[-1]-1)),
                front_difference=abs(front-front_position(previous.z,previous.theta[-1]))/p["length"])
        history.append(entry)
        previous=result
    last=history[-1]
    study.check("last two reacting grids theta","spatial convergence",last["theta_difference"],1e-3)
    study.check("last two reacting grids uptake","spatial convergence",last["relative_uptake_difference"],1e-3)
    study.check("last two reacting grids front/L","spatial convergence",last["front_difference"],1e-3)
    base=pulse_run(p,s,identifier,s["grids"][-1],boundary="flux",tight=False)
    study.record("finest_grid_time_base",base,1.)
    study.check("finest grid temporal theta","temporal convergence",np.max(np.abs(base.theta[-1]-previous.theta[-1])),1e-5)
    study.check("finest grid temporal uptake","temporal convergence",abs(base.captured_moles[-1]/previous.captured_moles[-1]-1),1e-5)
    return study.save(extra={"history":history})


def manufactured():
    study=Study("manufactured")
    p,s,identifier=study.case("manufactured")
    reference=ManufacturedSolution(p["length"],p["concentration_scale"],p["decay"],p["base_theta"],p["theta_amplitude"])
    histories={}
    for u in s["velocities"]:
        entries=[]
        for n in s["grids"]:
            print(f"MMS u={u}, N={n}",flush=True)
            r=geometry(p|{"velocity":u},n)
            surface=FiniteCapacity(p["capacity"],p["capture_velocity"])
            def forcing(t,z):
                return reference.source_averages(t,z,r.dz,velocity=u,diffusivity=r.diffusivity,
                    area_ratio=r.reactive_perimeter/r.area,capture_velocity=surface.capture_velocity,capacity=surface.capacity)
            c0,theta0=reference.averages(0.,r.z,r.dz)
            result=solve_1d(r,surface,[TransportSegment(p["duration"],ConcentrationBoundary(0.,0.))],
                concentration_scale=p["concentration_scale"],initial_c=c0,initial_theta=theta0,
                artificial_source=forcing,source_id="continuous-sine-MMS-analytic-cell-averages-v1",
                options=options(s,tight=True),provenance_id=identifier,
                output_times=np.linspace(0,p["duration"],s["output_samples"]))
            name=f"mms_u{u:g}_{n}"
            study.record(name,result,p["concentration_scale"],source=True)
            cexact,thexact=reference.averages(p["duration"],r.z,r.dz)
            # Evaluate the discrete operator on exact cell averages at a fixed
            # independent time, retaining the boundary cells in the full L1 norm.
            tt=.2
            cc,th=reference.averages(tt,r.z,r.dz)
            dc,dt=reference.derivatives(tt,r.z,r.dz)
            sg,st=forcing(tt,r.z)
            rate=surface.rate(cc,th)
            residual=(-np.diff(face_fluxes(cc,r,ConcentrationBoundary(0.,0.)))/r.dz
                -r.reactive_perimeter/r.area*rate+sg-dc)
            residual_theta=rate/surface.capacity+st-dt
            entry=dict(cells=n,dz=r.dz,c_error=normalized_l1(result.c[-1],cexact),
                theta_error=float(np.mean(np.abs(result.theta[-1]-thexact))),
                operator_l1=float(np.mean(np.abs(residual))),
                operator_interior_l1=float(np.mean(np.abs(residual[1:-1]))),
                operator_boundary_max=float(np.max(np.abs(residual[[0,-1]]))),
                surface_operator_l1=float(np.mean(np.abs(residual_theta))))
            if entries:
                for key in ("c_error","theta_error","operator_l1"):
                    entry[key+"_order"]=float(np.log2(entries[-1][key]/entry[key]))
            entries.append(entry)
            study.data[name+"_exact_c"]=cexact
            study.data[name+"_exact_theta"]=thexact
        expected=s["expected_order_advection"] if u else s["expected_order_diffusion"]
        for key in ("c_error","theta_error","operator_l1"):
            observed=entries[-1][key+"_order"]
            study.check(f"MMS u={u:g} {key} order","spatial convergence",abs(observed-expected),s["order_tolerance"],observed=observed,expected=expected)
        histories[str(u)]=entries
    return study.save(extra={"histories":histories})


def truncation():
    study=Study("truncation")
    p,s,identifier=study.case("domain-truncation")
    results=[]
    for extension in s["extensions"]:
        values=p|{"length":p["base_length"]*extension}
        n=s["cells_per_base_length"]*extension
        print(f"Truncation {extension}L, {n} cells",flush=True)
        result=pulse_run(values,s,identifier,n)
        study.record(f"domain_{extension}L",result,1.,upper_bound=True)
        results.append(result)
    a,b=results
    if not np.array_equal(a.t,b.t) or not np.array_equal(a.z[:s["cells_per_base_length"]],b.z[:s["cells_per_base_length"]]):
        raise ValueError("Truncation comparison requires matched physical times and cells")
    theta_diff=float(np.max(np.abs(a.theta[:,:s["cells_per_base_length"]]-b.theta[:,:s["cells_per_base_length"]])))
    study.check("10L versus 20L theta on [0,L]","domain truncation",theta_diff,1e-4)
    # The comparison must contain a reacting, partially completed front.
    front=front_position(a.z[:s["cells_per_base_length"]],a.theta[-1,:s["cells_per_base_length"]])
    study.check("truncation case has nonzero uptake","domain truncation",0. if a.captured_moles[-1]>0 else 1.,0.,front=front)
    study.data["truncation_t"]=a.t
    study.data["truncation_theta_difference"]=a.theta[:,:s["cells_per_base_length"]]-b.theta[:,:s["cells_per_base_length"]]
    return study.save(extra={"max_theta_difference":theta_diff,"front":front})


def report():
    documents={g:json.loads((OUT/f"{g}.json").read_text()) for g in GROUPS}
    current=hashes()
    for group,data in documents.items():
        if data["code_sha256"] != current:
            raise ValueError(f"Stale engine source for {group}; rerun affected study")
        for name,config in data["case_configs"].items():
            if config != json.loads((ROOT/f"config/synthetic/phase1-{name}.json").read_text()):
                raise ValueError(f"Changed case configuration for {group}/{name}")
    rows=[row for data in documents.values() for row in data["checks"]]
    categories={category:bool([r for r in rows if r["category"]==category]) and
                all(r["passed"] for r in rows if r["category"]==category) for category in GATE_CATEGORIES}
    if not all(run["exact_segment_carryover"] for d in documents.values() for run in d["runs"]):
        categories["boundary conditions"]=False
    gate="PASS" if all(categories.values()) else "FAIL"
    payload=dict(decision=gate,categories=categories,checks=rows,code_sha256=current,
        limitations=["Synthetic mathematical verification only; no experimental validity.",
            "Constant coefficients and one finite-capacity half-cycle; no full-cycle/GPC/QCM closure.",
            "Bounds and ledger errors are checked at stored output times, not proven for every continuous time.",
            "Radau/BDF share the same spatial discretization; independent analytical/MMS evidence checks spatial accuracy.",
            "The full planned studies remain separate from any dimensional benchmark."],
        total_elapsed_seconds=sum(d["elapsed_seconds"]+d["extra"].get("reused_elapsed_seconds",0.) for d in documents.values()))
    (OUT/"gate.json").write_text(json.dumps(payload,indent=2)+"\n")
    lines=["# Phase 1 gate", "", "```text", "PHASE 1 GATE", ""]
    lines += [f"[{'PASS' if passed else 'FAIL'}] {category}" for category,passed in categories.items()]
    lines += ["",f"Decision: {gate}","```","","All cases use explicitly synthetic inputs.","",
        "## Evidence","","Commands executed from the project directory:","","```sh",
        ".venv/bin/python -m pytest -q",
        "OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 PYTHONPATH=src .venv/bin/python scripts/verify_phase1.py --group all",
        "OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 PYTHONPATH=src .venv/bin/python scripts/verify_phase1.py --group transport --resume",
        "PYTHONPATH=src .venv/bin/python scripts/verify_phase1.py --group report","```","",
        "The same studies may be run independently with --group basic, transport, temporal, spatial, manufactured, or truncation, followed by --group report.","",
        "| Check | Error or deviation | Criterion | Result |","|---|---:|---:|---|"]
    lines += [f"| {r['name']} | {r['error']:.6e} | {r['tolerance']:.2e} | {'PASS' if r['passed'] else 'FAIL'} |" for r in rows]
    lines += ["","## Refinement diagnosis","",
        "The initial 4,000-cell advection-diffusion pulse error was 1.502977e-3, above the 1e-3 criterion. The same case was extended to 8,000 cells. The original failed attempt and runner are preserved under attempt-1/; no physical input or tolerance was changed.",
        "","## Material limitations",""]+[f"- {x}" for x in payload["limitations"]]
    failures=[r["name"] for r in rows if not r["passed"]]
    lines += ["","## Blocking issues","", "None for this mathematical gate." if not failures else "\n".join(f"- {x}" for x in failures),"",
              "Phase 2 has not started. Stop here for the next phase instruction.",""]
    (OUT/"gate.md").write_text("\n".join(lines))
    import csv
    with (OUT/"conservation.csv").open("w",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=["study","run","max_relative_ledger","max_absolute_ledger","final_entered","final_escaped","final_capture"],lineterminator="\n")
        writer.writeheader()
        for group,data in documents.items():
            for run in data["runs"]:
                writer.writerow(dict(study=group,run=run["name"],**{k:run[k] for k in writer.fieldnames[2:]}))
    figures(documents)
    print(json.dumps(dict(decision=gate,categories=categories,checks=len(rows))),flush=True)
    return gate=="PASS"


def figures(documents):
    os.environ.setdefault("MPLCONFIGDIR",str(ROOT/"work/matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import NullFormatter
    FIGURES.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({"font.size":10,"axes.grid":True,"grid.alpha":.2,"figure.dpi":160})
    fig,axes=plt.subplots(1,3,figsize=(13,3.8),layout="constrained")
    transport_history=documents["transport"]["extra"]["histories"]
    for ax,(name,entries) in zip(axes,transport_history.items()):
        ax.loglog([x["cells"] for x in entries],[x["error"] for x in entries],"o-",label="Measured spatial L1")
        tol=1e-2 if name=="advection-pulse" else 1e-3
        ax.axhline(tol,color="firebrick",ls="--",label="Acceptance criterion")
        ax.set(title=name.replace("-"," "),xlabel="Cells",ylabel="Normalized L1 error")
        ax.set_xticks([x["cells"] for x in entries],labels=[f"{x['cells']:,}" for x in entries])
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.legend(fontsize=8)
    fig.suptitle("Nonreacting analytical pulse verification — synthetic cases")
    fig.savefig(FIGURES/"analytical-convergence.png")
    plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(10,4),layout="constrained")
    for u,entries in documents["manufactured"]["extra"]["histories"].items():
        for ax,key,label in zip(axes,["c_error","theta_error"],["Gas normalized L1","Coverage absolute L1"]):
            ax.loglog([e["dz"] for e in entries],[e[key] for e in entries],"o-",label=f"u={u} m/s")
            ax.set(xlabel="Cell width (m)",ylabel=label)
            ax.set_xticks([e["dz"] for e in entries],labels=[f"{e['dz']:.6g}" for e in entries])
            ax.xaxis.set_minor_formatter(NullFormatter())
            ax.legend()
    fig.suptitle("Continuous manufactured solution — first-order advection / second-order diffusion")
    fig.savefig(FIGURES/"manufactured-convergence.png")
    plt.close(fig)
    arrays=np.load(OUT/"spatial.npz")
    history=documents["spatial"]["extra"]["history"]
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout="constrained")
    fig.suptitle("Synthetic single-half-cycle spatial convergence")
    for entry in history:
        name=f"reacting_{entry['cells']}"
        axes[0].plot(arrays[name+"_z"],arrays[name+"_theta"],label=f"N={entry['cells']}")
    axes[0].axhline(.5,color="grey",ls="--",lw=.8)
    axes[0].set(xlabel="z (m)",ylabel="Occupied capacity",title="Reacting pulse/purge at 1.75 s")
    axes[0].legend()
    for key,label in [("theta_difference","Max coverage"),("relative_uptake_difference","Relative uptake"),("front_difference","Front / L")]:
        axes[1].loglog([h["cells"] for h in history[1:]],[h[key] for h in history[1:]],"o-",label=label)
    axes[1].axhline(1e-3,color="firebrick",ls="--",label="Criterion")
    axes[1].set(xlabel="Fine-grid cells",ylabel="Difference between successive grids",title="Actual spatial convergence")
    axes[1].set_xticks([h["cells"] for h in history[1:]],labels=[f"{h['cells']:,}" for h in history[1:]])
    axes[1].xaxis.set_minor_formatter(NullFormatter())
    axes[1].legend(fontsize=8)
    fig.savefig(FIGURES/"reacting-convergence.png")
    plt.close(fig)
    temporal=documents["temporal"]["checks"]
    temporal=[x for x in temporal if x["category"] in ("temporal convergence","independent solver comparison")]
    fig,axes=plt.subplots(1,2,figsize=(12,4),layout="constrained")
    axes[0].barh([x["name"] for x in temporal],[max(x["error"],1e-16) for x in temporal])
    axes[0].axvline(1e-5,color="firebrick",ls="--")
    axes[0].set(xscale="log",xlabel="Error (absolute coverage / relative uptake)",title="Temporal refinement and solver comparison")
    trunc=np.load(OUT/"truncation.npz")
    axes[1].plot(trunc["truncation_t"],np.max(np.abs(trunc["truncation_theta_difference"]),axis=1))
    axes[1].axhline(1e-4,color="firebrick",ls="--",label="Criterion")
    axes[1].set(xlabel="Time (s)",ylabel="Max |theta_10L - theta_20L| on [0,L]",title="Nontrivial reacting domain truncation")
    axes[1].set_yscale("symlog",linthresh=1e-12)
    axes[1].legend()
    fig.savefig(FIGURES/"time-and-truncation.png")
    plt.close(fig)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group",choices=[*GROUPS,"report","all"],default="all")
    parser.add_argument("--resume",action="store_true",help="For transport only: reuse unchanged levels and compute appended grids")
    args=parser.parse_args()
    if args.resume and args.group!="transport":
        parser.error("--resume applies only to --group transport")
    functions={"basic":basic,"transport":transport,"temporal":temporal,"spatial":spatial,
               "manufactured":manufactured,"truncation":truncation,"report":report}
    selected=[*GROUPS,"report"] if args.group=="all" else [args.group]
    succeeded=True
    for group in selected:
        succeeded=(transport(resume=True) if args.resume else functions[group]()) and succeeded
    raise SystemExit(0 if succeeded else 1)
