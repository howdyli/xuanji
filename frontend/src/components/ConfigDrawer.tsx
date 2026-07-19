// --- Config Drawer (slide-in panel) ---
import { useState } from 'react'

export function ConfigDrawer({ onClose }: { onClose: () => void }) {
  const [activeModel, setActiveModel] = useState(0)
  const [activeSkills, setActiveSkills] = useState(['文档生成', '数据分析', 'PPT 制作'])
  const models = [
    { name: '灵享妙语 Pro', desc: '长文本 · 精细推理', avatar: '灵', gradient: 'linear-gradient(135deg, #7f77dd, #534ab7)', tags: ['推理', '长文', '创作'] },
    { name: 'Chat+', desc: '多轮对话 · 代码生成', avatar: 'C', gradient: '#378add', tags: ['代码', '对话', '分析'] },
    { name: 'Auto', desc: '自动规划 · 工具调用', avatar: 'A', gradient: '#2d9e6b', tags: ['规划', '工具', '自动化'] },
  ]
  const skills = [
    { name: '文档生成', freq: 12 },
    { name: '数据分析', freq: 10 },
    { name: 'PPT 制作', freq: 8 },
    { name: '翻译润色', freq: 6 },
    { name: '代码审查', freq: 4 },
    { name: '会议纪要', freq: 3 },
  ]
  const sortedSkills = [...skills].sort((a, b) => b.freq - a.freq)

  const toggleSkill = (skill: string) => {
    setActiveSkills(prev =>
      prev.includes(skill) ? prev.filter(s => s !== skill) : [...prev, skill]
    )
  }

  return (
    <>
      <div className="px-4 py-3.5 border-b border-[rgba(0,0,0,0.08)] flex items-center justify-between">
        <span className="text-[13px] font-semibold text-[#1a1917]">智能配置</span>
        <button
          onClick={onClose}
          className="w-[28px] h-[28px] rounded-[6px] bg-[#f0efe9] border border-[rgba(0,0,0,0.08)] flex items-center justify-center text-[14px] text-[#6b6963] hover:bg-[#e5e4de] transition-colors"
        >
          ×
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3.5 d-scroll">
        {/* Model switcher */}
        <div className="mb-5">
          <div className="text-[10px] font-medium uppercase tracking-wider text-[#9b9892] mb-2">当前模型</div>
          {models.map((m, i) => (
            <button
              key={m.name}
              onClick={() => setActiveModel(i)}
              className={`w-full flex items-start gap-2.5 p-2.5 rounded-[10px] border mb-1.5 transition-all duration-200 cursor-pointer ${
                activeModel === i ? 'border-[#4F6EF7] ws-model-pulse' : 'border-[rgba(0,0,0,0.08)] hover:bg-[#f0efe9]'
              }`}
            >
              <div className="w-7 h-7 rounded-full flex items-center justify-center text-[12px] font-semibold text-white shrink-0 mt-0.5" style={{ background: m.gradient }}>{m.avatar}</div>
              <div className="flex-1 min-w-0 text-left">
                <div className="text-[12px] font-medium text-[#1a1917] leading-tight">{m.name}</div>
                <div className="text-[10px] text-[#9b9892] mb-1">{m.desc}</div>
                <div className="flex gap-1 flex-wrap">
                  {m.tags.map(t => (
                    <span key={t} className="text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: 'rgba(79, 110, 247, 0.08)', color: '#4F6EF7' }}>{t}</span>
                  ))}
                </div>
              </div>
              {activeModel === i ? (
                <div className="w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 mt-1" style={{ borderColor: '#4F6EF7' }}>
                  <div className="w-2 h-2 rounded-full" style={{ background: '#4F6EF7' }} />
                </div>
              ) : null}
            </button>
          ))}
        </div>

        {/* Common skills */}
        <div className="mb-5">
          <div className="text-[10px] font-medium uppercase tracking-wider text-[#9b9892] mb-2">常用技能</div>
          <div className="flex flex-wrap gap-1.5">
            {sortedSkills.map((skill, si) => (
              <button
                key={skill.name}
                onClick={() => toggleSkill(skill.name)}
                className={`px-2.5 py-1 rounded-full text-[11px] border transition-all duration-150 active:scale-95 ${
                  activeSkills.includes(skill.name)
                    ? 'border-[#4F6EF7] text-[#4F6EF7]'
                    : 'bg-[#f0efe9] border-[rgba(0,0,0,0.08)] text-[#6b6963] hover:border-[#4F6EF7] hover:text-[#4F6EF7]'
                }`}
              >
                {si < 3 && <span className="text-[9px] mr-0.5">★</span>}{skill.name}
              </button>
            ))}
          </div>
        </div>

        {/* Tips — icon card style */}
        <div className="space-y-1.5">
          {[
            { icon: '@', text: '@数据分析师 帮你分析数据', color: '#4F6EF7' },
            { icon: '#', text: '#文件 快速引用知识库文档', color: '#1a6fbf' },
            { icon: '/', text: '/report 一键生成日报', color: '#2d9e6b' },
          ].map(tip => (
            <div key={tip.icon} className="flex items-center gap-2.5 bg-[#f0efe9] rounded-[8px] p-2.5">
              <span className="w-6 h-6 rounded-[5px] flex items-center justify-center text-[12px] font-bold text-white shrink-0" style={{ background: tip.color }}>{tip.icon}</span>
              <span className="text-[11px] text-[#6b6963]">{tip.text}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
