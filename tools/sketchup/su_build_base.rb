# Shared rules for every SketchUp builder (Nick's pattern, kept generic):
#  - one start_operation per run = one undo step; abort_operation on ANY error, so the model stays clean;
#  - each builder owns ONE named root group: it erases its old one and rebuilds it (re-runnable);
#  - every element goes on a tag, gets a material, and the run returns a report string (counts, heights).
# Usage inside a builder module:
#   SuBuild.run('Walls from DWG') do |b|          # b is a SuBuild::Ctx
#     b.extrude(b.root.entities, [[0,0],[5,0],[5,0.25],[0,0.25]], 0.0, 2.8, tag: 'DWG Walls', mat: ['RC wall', [170,170,165]])
#     b.count(:walls)
#   end   # -> "Walls from DWG: walls 1 (0.1 s)"
# All inputs in metres.
module SuBuild
  class Ctx
    attr_reader :model, :root, :counts, :notes
    def initialize(model, root)
      @model, @root, @counts, @notes = model, root, Hash.new(0), []
    end

    def pt(xy, z) Geom::Point3d.new(xy[0].to_f.m, xy[1].to_f.m, z.to_f.m) end

    def tag(name)
      @model.layers[name] || @model.layers.add(name)
    end

    def material(name, rgb, alpha = nil)
      m = @model.materials[name] || @model.materials.add(name)
      m.color = Sketchup::Color.new(*rgb) if rgb
      m.alpha = alpha if alpha
      m
    end

    # Closed 2D outline (list of [x, y], last point may repeat the first) extruded from z0 by height,
    # as its own group inside `ents`. Returns the group, or nil (and a note) if the outline is invalid.
    def extrude(ents, outline, z0, height, tag: nil, mat: nil, name: nil, holes: [])
      pts = clean(outline)
      return note("skipped outline with #{pts.size} points#{name ? " (#{name})" : ''}") if pts.size < 3
      return note("skipped #{name}: height #{height} <= 0") if height.to_f <= 0
      g = ents.add_group
      g.name = name if name
      f = begin
        g.entities.add_face(pts.map { |p| pt(p, z0) })
      rescue ArgumentError => e
        nil
      end
      return (g.erase!; note("could not make a face#{name ? " for #{name}" : ''}")) unless f
      (holes || []).each do |h|
        hp = clean(h)
        next if hp.size < 3
        begin
          hf = g.entities.add_face(hp.map { |p| pt(p, z0) })
          hf.erase! if hf && hf.valid?
        rescue ArgumentError
          note("hole skipped in #{name}")
        end
      end
      f = g.entities.grep(Sketchup::Face).max_by(&:area)        # the outer face (holes may have split it)
      f.reverse! if f.normal.z < 0
      f.pushpull(height.to_f.m)
      g.layer = self.tag(tag) if tag
      g.material = self.material(*mat) if mat
      g
    end

    # drop the closing point and consecutive duplicates (SketchUp rejects zero-length edges)
    def clean(path)
      pts = []
      path.each { |p| pts << p unless pts.last && (pts.last[0] - p[0]).abs < 1e-6 && (pts.last[1] - p[1]).abs < 1e-6 }
      pts.pop if pts.size > 1 && (pts.first[0] - pts.last[0]).abs < 1e-6 && (pts.first[1] - pts.last[1]).abs < 1e-6
      pts
    end

    def count(key, n = 1) @counts[key] += n end
    def note(msg) @notes << msg; nil end
  end

  # Erases the previous root group with this name, builds a new one in the block, all as one undo step.
  def self.run(root_name, tag_name = nil)
    model = Sketchup.active_model
    t0 = Time.now
    model.start_operation(root_name, true)
    begin
      model.entities.grep(Sketchup::Group).select { |g| g.name == root_name }.each(&:erase!)
      root = model.entities.add_group
      root.name = root_name
      ctx = Ctx.new(model, root)
      root.layer = ctx.tag(tag_name) if tag_name
      yield ctx
      model.commit_operation
    rescue Exception
      model.abort_operation
      raise
    end
    parts = ctx.counts.map { |k, v| "#{k} #{v}" }
    msg = "#{root_name}: #{parts.empty? ? 'nothing built' : parts.join(', ')} (#{(Time.now - t0).round(1)} s)"
    msg += "\nnotes:\n  " + ctx.notes.first(30).join("\n  ") unless ctx.notes.empty?
    msg
  end
end
