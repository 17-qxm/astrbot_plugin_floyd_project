// 骨架屏组件 — 加载时显示灰色占位块（带 shimmer 动画）。

export const Skeleton = {
  name: "Skeleton",
  props: {
    lines: { type: Number, default: 3 },
  },
  template: `
    <div>
      <div v-for="i in lines" :key="i" class="skeleton skel-line"></div>
    </div>
  `,
};

export const SkeletonRows = {
  name: "SkeletonRows",
  props: {
    rows: { type: Number, default: 4 },
  },
  template: `
    <div>
      <div v-for="i in rows" :key="i" class="ch-row" style="pointer-events:none;">
        <div class="skeleton" style="width:36px;height:14px;"></div>
        <div class="skeleton" style="flex:1;height:14px;"></div>
        <div class="skeleton" style="width:50px;height:18px;border-radius:20px;"></div>
      </div>
    </div>
  `,
};
