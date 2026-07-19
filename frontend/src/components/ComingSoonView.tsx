// --- Coming Soon View (placeholder for unimplemented modules) ---
export function ComingSoonView({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6">
      <div className="w-16 h-16 rounded-2xl bg-blue-50 flex items-center justify-center text-blue-500 mb-5">
        {icon}
      </div>
      <h2 className="text-[20px] font-semibold text-gray-800 mb-2">{title}</h2>
      <p className="text-[14px] text-gray-400 text-center max-w-sm mb-6">{description}</p>
      <span className="px-4 py-1.5 rounded-full bg-gray-100 text-[12px] text-gray-500 font-medium">
        敬请期待
      </span>
    </div>
  )
}
