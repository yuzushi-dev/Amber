"""
Sample Data Seed API
====================

Endpoint for seeding sample data for onboarding and demos.
Uses Wikipedia public domain content.
"""

import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from src.api.deps import get_db
from src.api.schemas.base import ResponseSchema
from src.shared.context import get_current_tenant

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


# --- Sample Data ---

SAMPLE_DATASETS = {
    "solar_system": {
        "name": "Solar System",
        "description": "Educational content about planets and the solar system",
        "documents": [
            {
                "title": "The Sun",
                "content": """# The Sun

The Sun is the star at the center of the Solar System. It is a nearly perfect ball of hot plasma, heated to incandescence by nuclear fusion reactions in its core.

## Physical Characteristics

The Sun has a diameter of about 1.39 million kilometers (864,000 miles), or 109 times that of Earth. Its mass is about 330,000 times that of Earth, comprising about 99.86% of the total mass of the Solar System.

## Composition

Roughly three-quarters of the Sun's mass consists of hydrogen (~73%); the rest is mostly helium (~25%), with much smaller quantities of heavier elements, including oxygen, carbon, neon, and iron.

## Energy Production

The Sun's core fuses about 600 million tons of hydrogen into helium every second, converting 4 million tons of matter into energy every second as a result. This energy, which can take between 10,000 and 170,000 years to escape the core, is the source of the Sun's light and heat.

## Solar Activity

The Sun's activity varies on an approximately 11-year cycle known as the solar cycle. This cycle affects the number of sunspots, solar flares, and coronal mass ejections.
"""
            },
            {
                "title": "Earth",
                "content": """# Earth

Earth is the third planet from the Sun and the only astronomical object known to harbor life. About 29.2% of Earth's surface is land consisting of continents and islands.

## Orbital Characteristics

Earth orbits the Sun at an average distance of about 150 million kilometers (93 million miles) every 365.25 days. This distance is defined as one Astronomical Unit (AU).

## Atmosphere

Earth's atmosphere is composed of 78% nitrogen, 21% oxygen, and 1% other gases. The atmosphere protects life on Earth by absorbing ultraviolet solar radiation, warming the surface through heat retention, and reducing temperature extremes.

## The Moon

Earth has one natural satellite, the Moon. It is the fifth largest moon in the Solar System and the largest relative to its planet. The Moon stabilizes Earth's axial tilt and gradually slows its rotation.

## Life on Earth

Earth is the only place in the universe known to harbor life. Life on Earth evolved from single-celled organisms approximately 3.8 billion years ago.
"""
            },
            {
                "title": "Mars",
                "content": """# Mars

Mars is the fourth planet from the Sun and the second-smallest planet in the Solar System, being larger than only Mercury. In the English language, Mars is named for the Roman god of war.

## Physical Characteristics

Mars has approximately half the diameter of Earth, with a surface area only slightly less than the total area of Earth's dry land. Mars is less dense than Earth, having about 15% of Earth's volume and 11% of Earth's mass.

## Atmosphere

The atmosphere of Mars consists of about 96% carbon dioxide, 1.93% argon and 1.89% nitrogen along with traces of oxygen and water. The atmospheric pressure on the Martian surface averages about 600 pascals, about 0.6% of Earth's surface pressure.

## Moons

Mars has two small natural satellites, Phobos and Deimos. These moons are thought to be captured asteroids.

## Exploration

Mars has been explored by numerous spacecraft, including orbiters, landers, and rovers. As of 2024, there are active missions including NASA's Perseverance rover and Ingenuity helicopter.

## Potential for Life

Scientists have long speculated about the possibility of life on Mars, particularly microbial life. Evidence of past water suggests that conditions may have been favorable for life billions of years ago.
"""
            }
        ]
    },
    "technology": {
        "name": "Technology Concepts",
        "description": "Technical documentation about computing and AI",
        "documents": [
            {
                "title": "Machine Learning",
                "content": """# Machine Learning

Machine learning (ML) is a subset of artificial intelligence (AI) that enables systems to learn and improve from experience without being explicitly programmed.

## Types of Machine Learning

### Supervised Learning
The algorithm learns from labeled training data. Examples include classification and regression tasks.

### Unsupervised Learning
The algorithm finds patterns in unlabeled data. Examples include clustering and dimensionality reduction.

### Reinforcement Learning
The algorithm learns by interacting with an environment and receiving rewards or penalties.

## Common Algorithms

- **Linear Regression**: Predicts continuous values
- **Decision Trees**: Creates tree-like decision models
- **Neural Networks**: Mimics the human brain's structure
- **Support Vector Machines**: Finds optimal hyperplanes for classification

## Applications

Machine learning is used in:
- Image and speech recognition
- Natural language processing
- Recommendation systems
- Fraud detection
- Autonomous vehicles
"""
            },
            {
                "title": "Neural Networks",
                "content": """# Neural Networks

A neural network is a series of algorithms that attempts to recognize underlying relationships in data through a process that mimics the way the human brain operates.

## Architecture

### Input Layer
Receives the initial data for processing.

### Hidden Layers
Process inputs through weighted connections. Deep neural networks have multiple hidden layers.

### Output Layer
Produces the final prediction or classification.

## Types of Neural Networks

### Feedforward Neural Networks
The simplest type where connections don't form cycles.

### Convolutional Neural Networks (CNNs)
Specialized for processing grid-like data such as images.

### Recurrent Neural Networks (RNNs)
Designed for sequential data like time series and text.

### Transformer Networks
Use attention mechanisms for parallel processing of sequences.

## Training

Neural networks learn through backpropagation, adjusting weights based on the error between predicted and actual outputs.
"""
            }
        ]
    }
}


class SeedRequest(BaseModel):
    """Request to seed sample data."""
    dataset: str = "solar_system"  # solar_system or technology


class SeedResponse(BaseModel):
    """Response after seeding."""
    documents_created: int
    dataset_name: str
    message: str


@router.post("/seed-sample-data", response_model=ResponseSchema[SeedResponse])
async def seed_sample_data(
    request: SeedRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Seed sample data for onboarding and demos.
    
    Available datasets:
    - solar_system: Educational content about planets
    - technology: Technical documentation about AI/ML
    """
    if request.dataset not in SAMPLE_DATASETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown dataset '{request.dataset}'. Available: {list(SAMPLE_DATASETS.keys())}"
        )
    
    tenant_id = get_current_tenant() or "default"
    dataset = SAMPLE_DATASETS[request.dataset]
    
    try:
        from src.core.models.document import Document
        from src.core.state.machine import DocumentStatus
        from src.core.models.chunk import Chunk
        from src.shared.identifiers import generate_document_id, generate_chunk_id
        import hashlib
        
        documents_created = 0
        
        for doc_data in dataset["documents"]:
            # Generate document ID and hash
            doc_id = generate_document_id()
            content_bytes = doc_data["content"].encode("utf-8")
            content_hash = hashlib.sha256(content_bytes).hexdigest()
            
            # Create document
            document = Document(
                id=doc_id,
                tenant_id=tenant_id,
                filename=f"{doc_data['title'].lower().replace(' ', '_')}.md",
                content_hash=content_hash,
                storage_path=f"sample/{doc_id}",  # Virtual path for sample data
                status=DocumentStatus.READY,
                domain="EDUCATIONAL" if request.dataset == "solar_system" else "TECHNICAL",
                source_type="sample",
                metadata_={"sample_dataset": request.dataset, "title": doc_data["title"]}
            )
            db.add(document)
            
            # Create a single chunk for simplicity
            chunk = Chunk(
                id=generate_chunk_id(doc_id, 0),
                document_id=doc_id,
                index=0,
                content=doc_data["content"],
                tokens=len(doc_data["content"].split()),  # Rough estimate
                metadata_={"title": doc_data["title"]}
            )
            db.add(chunk)
            
            documents_created += 1
        
        await db.commit()
        
        logger.info(f"Seeded {documents_created} documents from '{request.dataset}' for tenant {tenant_id}")
        
        # TODO: Trigger embedding generation in background
        # background_tasks.add_task(generate_embeddings_for_tenant, tenant_id)
        
        return ResponseSchema(
            data=SeedResponse(
                documents_created=documents_created,
                dataset_name=dataset["name"],
                message=f"Successfully seeded {documents_created} sample documents. Run embedding pipeline to enable search."
            ),
            message="Sample data seeded successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to seed sample data: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to seed sample data: {str(e)}"
        )


@router.get("/sample-datasets", response_model=ResponseSchema[dict])
async def list_sample_datasets():
    """List available sample datasets."""
    datasets = {
        name: {
            "name": data["name"],
            "description": data["description"],
            "document_count": len(data["documents"])
        }
        for name, data in SAMPLE_DATASETS.items()
    }
    
    return ResponseSchema(
        data=datasets,
        message="Available sample datasets"
    )
