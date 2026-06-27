from api.templates.descriptive import run_descriptive
from api.templates.before_after_mean import run_before_after_mean
from api.templates.before_after_pct import run_before_after_pct
from api.templates.run_chart import run_run_chart
from api.templates.p_chart import run_p_chart
from api.templates.u_c_chart import run_u_c_chart

TEMPLATE_REGISTRY = {
    "descriptive_summary": run_descriptive,
    "before_after_mean": run_before_after_mean,
    "before_after_pct": run_before_after_pct,
    "run_chart": run_run_chart,
    "p_chart": run_p_chart,
    "u_c_chart": run_u_c_chart,
}
