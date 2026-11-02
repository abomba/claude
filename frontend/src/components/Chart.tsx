import { BoxplotChart, ScatterChart } from "echarts/charts";
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import langPL from "echarts/i18n/langPL-obj.js";
import { useEffect, useRef } from "react";

echarts.use([ScatterChart, BoxplotChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, SVGRenderer]);
echarts.registerLocale("PL", langPL as Parameters<typeof echarts.registerLocale>[1]);

export function Chart({ option, testId }: { option: echarts.EChartsCoreOption; testId?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "svg", locale: "PL" });
    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [option]);
  return <div ref={ref} className="chart" data-testid={testId} />;
}
