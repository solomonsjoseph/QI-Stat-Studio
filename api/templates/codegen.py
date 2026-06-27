def generate_r_code(template: str, params: dict) -> str:
    if template == "descriptive_summary":
        cols = ", ".join(f'"{c}"' for c in params.get("value_cols", []))
        grp = params.get("group_col", "group")
        return (f'library(dplyr)\ndf <- read.csv("your_data.csv")\n'
                f'df |> group_by({grp}) |>\n'
                f'  summarise(across(c({cols}),\n'
                f'    list(n=~sum(!is.na(.)), mean=mean, sd=sd, median=median), na.rm=TRUE))')

    if template == "before_after_mean":
        gc = params.get("group_col", "period")
        vc = params.get("value_col", "value")
        pre = params.get("pre_val", "pre")
        post = params.get("post_val", "post")
        return (f'library(dplyr)\ndf <- read.csv("your_data.csv")\n'
                f'df${gc} <- trimws(tolower(df${gc}))\n'
                f'pre <- df[df${gc} == "{pre}", "{vc}"]\n'
                f'post <- df[df${gc} == "{post}", "{vc}"]\n'
                f'shapiro.test(pre); shapiro.test(post)\n'
                f'wilcox.test(pre, post)  # or t.test if normal')

    if template == "before_after_pct":
        gc = params.get("group_col", "period")
        oc = params.get("outcome_col", "outcome")
        pre = params.get("pre_val", "pre")
        post = params.get("post_val", "post")
        return (f'library(dplyr)\ndf <- read.csv("your_data.csv")\n'
                f'df${gc} <- trimws(tolower(df${gc}))\n'
                f'ct <- table(df[df${gc} %in% c("{pre}","{post}"), c("{gc}", "{oc}")])\n'
                f'chisq.test(ct)  # or fisher.test(ct) if expected < 5')

    if template == "run_chart":
        dc = params.get("date_col", "encounter_date")
        vc = params.get("value_col", "value")
        return (f'library(dplyr); library(ggplot2)\ndf <- read.csv("your_data.csv")\n'
                f'df${dc} <- as.Date(df${dc})\n'
                f'monthly <- df |> group_by(month=format({dc}, "%Y-%m")) |>\n'
                f'  summarise(mean_{vc}=mean({vc}, na.rm=TRUE))\n'
                f'med <- median(monthly$mean_{vc})\n'
                f'ggplot(monthly, aes(x=month, y=mean_{vc}, group=1)) + geom_line() + geom_point() +\n'
                f'  geom_hline(yintercept=med, color="red", linetype="dashed")')

    if template == "p_chart":
        dc = params.get("date_col", "encounter_date")
        nc = params.get("numerator_col", "outcome")
        return (f'library(dplyr); library(ggplot2)\ndf <- read.csv("your_data.csv")\n'
                f'df${dc} <- as.Date(df${dc})\n'
                f'monthly <- df |> group_by(month=format({dc}, "%Y-%m")) |>\n'
                f'  summarise(num=sum({nc},na.rm=TRUE), denom=n())\n'
                f'monthly$p <- monthly$num/monthly$denom\n'
                f'pbar <- mean(monthly$p); nbar <- mean(monthly$denom)\n'
                f'monthly$ucl <- pbar + 3*sqrt(pbar*(1-pbar)/nbar)\n'
                f'monthly$lcl <- pmax(0, pbar - 3*sqrt(pbar*(1-pbar)/nbar))')

    if template == "u_c_chart":
        dc = params.get("date_col", "encounter_date")
        cc = params.get("count_col", "count")
        return (f'library(dplyr)\ndf <- read.csv("your_data.csv")\n'
                f'df${dc} <- as.Date(df${dc})\n'
                f'monthly <- df |> group_by(month=format({dc}, "%Y-%m")) |>\n'
                f'  summarise(cnt=sum({cc},na.rm=TRUE))\n'
                f'cbar <- mean(monthly$cnt)\n'
                f'monthly$ucl <- cbar + 3*sqrt(cbar)\n'
                f'monthly$lcl <- pmax(0, cbar - 3*sqrt(cbar))')

    return f'# R code for template "{template}" not yet implemented.'
